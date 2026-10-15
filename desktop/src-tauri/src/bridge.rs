use serde::Serialize;
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    io::{self, BufRead, BufReader, BufWriter, Read, Write},
    path::PathBuf,
    process::{Child, ChildStderr, ChildStdin, Command, Stdio},
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
        mpsc::{self, Sender},
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};
use tauri::State;

pub const MAX_MESSAGE_BYTES: usize = 65_536;
const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(2);

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum BridgeErrorCode {
    DeviceOffline,
    CommandCanceled,
    Timeout,
    AuthFailed,
    InvalidInput,
    UnsupportedCapability,
    DeviceError,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BridgeError {
    pub code: BridgeErrorCode,
    pub message: &'static str,
}
impl BridgeError {
    fn new(code: BridgeErrorCode) -> Self {
        let message = match code {
            BridgeErrorCode::DeviceOffline => "Device is unreachable",
            BridgeErrorCode::CommandCanceled => "Command was canceled before completion",
            BridgeErrorCode::Timeout => "Device request timed out",
            BridgeErrorCode::AuthFailed => "Device authentication failed",
            BridgeErrorCode::InvalidInput => "Request is invalid",
            BridgeErrorCode::UnsupportedCapability => "Device does not support this operation",
            BridgeErrorCode::DeviceError => "Device operation failed",
        };
        Self { code, message }
    }
    fn protocol() -> Self {
        Self::new(BridgeErrorCode::DeviceError)
    }
    fn from_backend(code: &str) -> Self {
        let code = match code {
            "DEVICE_OFFLINE" => BridgeErrorCode::DeviceOffline,
            "COMMAND_CANCELED" => BridgeErrorCode::CommandCanceled,
            "TIMEOUT" => BridgeErrorCode::Timeout,
            "AUTH_FAILED" => BridgeErrorCode::AuthFailed,
            "INVALID_INPUT" => BridgeErrorCode::InvalidInput,
            "UNSUPPORTED_CAPABILITY" => BridgeErrorCode::UnsupportedCapability,
            _ => BridgeErrorCode::DeviceError,
        };
        Self::new(code)
    }
}

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum BackendMode {
    Mock,
    Fixture,
    Real,
}
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BridgeInfo {
    pub mode: BackendMode,
    pub available: bool,
    pub error: Option<BridgeError>,
}

enum ProcessConfig {
    Fixture,
    Real(PathBuf),
}
impl ProcessConfig {
    fn from_environment() -> Result<Option<Self>, BridgeError> {
        let mode = match std::env::var("SMART_HOME_TRAY_BACKEND_MODE") {
            Ok(mode) => Some(mode),
            Err(std::env::VarError::NotPresent) => None,
            Err(std::env::VarError::NotUnicode(_)) => {
                return Err(BridgeError::new(BridgeErrorCode::InvalidInput));
            }
        };
        let allow_real = std::env::var("SMART_HOME_TRAY_ALLOW_REAL").ok();
        let config = std::env::var_os("SMART_HOME_TRAY_CONFIG").map(PathBuf::from);
        Self::from_values(mode.as_deref(), allow_real.as_deref(), config)
    }
    fn from_values(
        mode: Option<&str>,
        allow_real: Option<&str>,
        config: Option<PathBuf>,
    ) -> Result<Option<Self>, BridgeError> {
        match mode {
            None | Some("mock") => Ok(None),
            Some("fixture") => Ok(Some(Self::Fixture)),
            Some("real") => {
                if allow_real != Some("1") {
                    return Err(BridgeError::new(BridgeErrorCode::InvalidInput));
                }
                let path = config
                    .filter(|path| path.is_absolute() && path.is_file())
                    .ok_or_else(|| BridgeError::new(BridgeErrorCode::InvalidInput))?;
                Ok(Some(Self::Real(path)))
            }
            Some(_) => Err(BridgeError::new(BridgeErrorCode::InvalidInput)),
        }
    }
    fn mode(&self) -> BackendMode {
        match self {
            Self::Fixture => BackendMode::Fixture,
            Self::Real(_) => BackendMode::Real,
        }
    }
    fn spawn(&self) -> io::Result<Child> {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..");
        let python_path = root.join("backend").join("src");
        let mut command = Command::new("python");
        command.arg("-u").arg("-m");
        match self {
            Self::Fixture => {
                command.arg("smart_home_tray.fixture");
            }
            Self::Real(path) => {
                command
                    .arg("smart_home_tray.cli")
                    .arg("--config")
                    .arg(path)
                    .arg("serve");
            }
        }
        command
            .current_dir(&root)
            .env("PYTHONPATH", python_path)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        command.spawn()
    }
}

struct RequestState {
    pending: HashMap<String, Sender<Result<Value, BridgeError>>>,
    failed: Option<BridgeError>,
}
struct Shared {
    requests: Mutex<RequestState>,
    next_id: AtomicU64,
}
#[derive(Clone)]
pub struct BridgeClient {
    shared: Arc<Shared>,
    stdin: Arc<Mutex<Option<BufWriter<ChildStdin>>>>,
    child: Arc<Mutex<Option<Child>>>,
    reader: Arc<Mutex<Option<JoinHandle<()>>>>,
    stderr: Arc<Mutex<Option<JoinHandle<()>>>>,
    timeout: Duration,
}
impl BridgeClient {
    fn spawn_config(config: &ProcessConfig) -> io::Result<Self> {
        Self::spawn_command(config.spawn()?)
    }
    fn spawn_command(mut child: Child) -> io::Result<Self> {
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| io::Error::other("stdin pipe missing"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| io::Error::other("stdout pipe missing"))?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| io::Error::other("stderr pipe missing"))?;
        let shared = Arc::new(Shared {
            requests: Mutex::new(RequestState {
                pending: HashMap::new(),
                failed: None,
            }),
            next_id: AtomicU64::new(1),
        });
        let reader_shared = shared.clone();
        let reader = thread::Builder::new()
            .name("tray-jsonl-reader".into())
            .spawn(move || read_responses(BufReader::new(stdout), reader_shared))?;
        let stderr_thread = thread::Builder::new()
            .name("tray-backend-stderr".into())
            .spawn(move || drain_stderr(stderr))?;
        Ok(Self {
            shared,
            stdin: Arc::new(Mutex::new(Some(BufWriter::new(stdin)))),
            child: Arc::new(Mutex::new(Some(child))),
            reader: Arc::new(Mutex::new(Some(reader))),
            stderr: Arc::new(Mutex::new(Some(stderr_thread))),
            timeout: REQUEST_TIMEOUT,
        })
    }
    pub fn request(&self, command: &'static str, payload: Value) -> Result<Value, BridgeError> {
        let id = format!(
            "req-{}",
            self.shared.next_id.fetch_add(1, Ordering::Relaxed)
        );
        let (sender, receiver) = mpsc::channel();
        let bytes =
            serde_json::to_vec(&json!({"requestId":id,"command":command,"payload":payload}))
                .map_err(|_| BridgeError::protocol())?;
        if bytes.len() > MAX_MESSAGE_BYTES {
            return Err(BridgeError::new(BridgeErrorCode::InvalidInput));
        }
        register_pending(&self.shared, id.clone(), sender)?;
        let write_result = self.stdin.lock().ok().and_then(|mut guard| {
            guard.as_mut().map(|stdin| {
                stdin
                    .write_all(&bytes)
                    .and_then(|_| stdin.write_all(b"\n"))
                    .and_then(|_| stdin.flush())
            })
        });
        match write_result {
            Some(Ok(())) => {}
            _ => {
                self.remove_pending(&id);
                self.fail_all(BridgeError::protocol());
                return Err(BridgeError::protocol());
            }
        }
        match receiver.recv_timeout(self.timeout) {
            Ok(result) => result,
            Err(mpsc::RecvTimeoutError::Timeout) => {
                self.remove_pending(&id);
                Err(BridgeError::new(BridgeErrorCode::Timeout))
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => Err(BridgeError::protocol()),
        }
    }
    fn remove_pending(&self, id: &str) {
        if let Ok(mut requests) = self.shared.requests.lock() {
            requests.pending.remove(id);
        }
    }
    fn fail_all(&self, error: BridgeError) {
        fail_shared(&self.shared, error);
    }
    pub fn shutdown(&self) {
        if let Ok(mut stdin) = self.stdin.lock() {
            stdin.take();
        }
        if let Ok(mut guard) = self.child.lock() {
            if let Some(child) = guard.as_mut() {
                let until = Instant::now() + SHUTDOWN_GRACE;
                while Instant::now() < until {
                    if child.try_wait().ok().flatten().is_some() {
                        break;
                    }
                    thread::sleep(Duration::from_millis(20));
                }
                if child.try_wait().ok().flatten().is_none() {
                    let _ = child.kill();
                }
                let _ = child.wait();
            }
            guard.take();
        }
        self.fail_all(BridgeError::protocol());
        if let Ok(mut handle) = self.reader.lock() {
            if let Some(handle) = handle.take() {
                let _ = handle.join();
            }
        }
        if let Ok(mut handle) = self.stderr.lock() {
            if let Some(handle) = handle.take() {
                let _ = handle.join();
            }
        }
    }
}
impl Drop for BridgeClient {
    fn drop(&mut self) {
        if Arc::strong_count(&self.child) == 1 {
            self.shutdown();
        }
    }
}

fn drain_stderr(mut stderr: ChildStderr) {
    let mut buffer = [0u8; 4096];
    while let Ok(read) = stderr.read(&mut buffer) {
        if read == 0 {
            break;
        }
    }
}
fn read_responses<R: BufRead>(mut reader: R, shared: Arc<Shared>) {
    loop {
        match read_bounded_line(&mut reader) {
            Ok(Some(line)) => match parse_response(&line) {
                Ok((id, result)) => {
                    let sender = shared
                        .requests
                        .lock()
                        .ok()
                        .and_then(|mut requests| requests.pending.remove(&id));
                    if let Some(sender) = sender {
                        let _ = sender.send(result);
                    }
                }
                Err(_) => {
                    fail_shared(&shared, BridgeError::protocol());
                    break;
                }
            },
            Ok(None) => {
                fail_shared(&shared, BridgeError::protocol());
                break;
            }
            Err(_) => {
                fail_shared(&shared, BridgeError::new(BridgeErrorCode::InvalidInput));
                break;
            }
        }
    }
}
fn fail_shared(shared: &Shared, error: BridgeError) {
    let pending = if let Ok(mut requests) = shared.requests.lock() {
        if requests.failed.is_none() {
            requests.failed = Some(error.clone());
        }
        requests
            .pending
            .drain()
            .map(|(_, sender)| sender)
            .collect::<Vec<_>>()
    } else {
        Vec::new()
    };
    for sender in pending {
        let _ = sender.send(Err(error.clone()));
    }
}
fn register_pending(
    shared: &Shared,
    id: String,
    sender: Sender<Result<Value, BridgeError>>,
) -> Result<(), BridgeError> {
    let mut requests = shared
        .requests
        .lock()
        .map_err(|_| BridgeError::protocol())?;
    if let Some(error) = &requests.failed {
        return Err(error.clone());
    }
    requests.pending.insert(id, sender);
    Ok(())
}
fn read_bounded_line<R: BufRead>(reader: &mut R) -> io::Result<Option<Vec<u8>>> {
    let mut output = Vec::new();
    loop {
        let available = reader.fill_buf()?;
        if available.is_empty() {
            return if output.is_empty() {
                Ok(None)
            } else if output.len() > MAX_MESSAGE_BYTES {
                Err(io::Error::new(io::ErrorKind::InvalidData, "line too long"))
            } else {
                Ok(Some(output))
            };
        }
        let newline = available.iter().position(|b| *b == b'\n');
        let count = newline.map(|n| n + 1).unwrap_or(available.len());
        let over = output.len().saturating_add(count) > MAX_MESSAGE_BYTES + 2;
        if !over {
            output.extend_from_slice(&available[..count]);
        }
        reader.consume(count);
        if over {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "line too long"));
        }
        if newline.is_some() {
            break;
        }
    }
    if output.last() == Some(&b'\n') {
        output.pop();
    }
    if output.last() == Some(&b'\r') {
        output.pop();
    }
    if output.len() > MAX_MESSAGE_BYTES {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "line too long"));
    }
    Ok(Some(output))
}
fn parse_response(line: &[u8]) -> Result<(String, Result<Value, BridgeError>), BridgeError> {
    if line.len() > MAX_MESSAGE_BYTES {
        return Err(BridgeError::new(BridgeErrorCode::InvalidInput));
    }
    let value: Value = serde_json::from_slice(line).map_err(|_| BridgeError::protocol())?;
    let object = value.as_object().ok_or_else(BridgeError::protocol)?;
    let id = object
        .get("requestId")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty() && s.len() <= 128)
        .ok_or_else(BridgeError::protocol)?
        .to_string();
    match (object.get("result"), object.get("error")) {
        (Some(result), None) if object.len() == 2 => Ok((id, Ok(result.clone()))),
        (None, Some(error)) if object.len() == 2 => {
            let error = error.as_object().ok_or_else(BridgeError::protocol)?;
            if error.len() != 2 {
                return Err(BridgeError::protocol());
            }
            let code = error
                .get("code")
                .and_then(Value::as_str)
                .ok_or_else(BridgeError::protocol)?;
            let message = error
                .get("message")
                .and_then(Value::as_str)
                .ok_or_else(BridgeError::protocol)?;
            if message.len() > 512 {
                return Err(BridgeError::protocol());
            }
            Ok((id, Err(BridgeError::from_backend(code))))
        }
        _ => Err(BridgeError::protocol()),
    }
}

pub struct BridgeState {
    info: BridgeInfo,
    client: Option<BridgeClient>,
}
impl BridgeState {
    pub fn new() -> Self {
        match ProcessConfig::from_environment() {
            Ok(None) => Self {
                info: BridgeInfo {
                    mode: BackendMode::Mock,
                    available: true,
                    error: None,
                },
                client: None,
            },
            Ok(Some(config)) => {
                let mode = config.mode();
                match BridgeClient::spawn_config(&config) {
                    Ok(client) => {
                        let ready = verify_backend_ready(&client).is_ok();
                        if ready {
                            Self {
                                info: BridgeInfo {
                                    mode,
                                    available: true,
                                    error: None,
                                },
                                client: Some(client),
                            }
                        } else {
                            client.shutdown();
                            Self {
                                info: BridgeInfo {
                                    mode,
                                    available: false,
                                    error: Some(BridgeError::protocol()),
                                },
                                client: None,
                            }
                        }
                    }
                    Err(_) => Self {
                        info: BridgeInfo {
                            mode,
                            available: false,
                            error: Some(BridgeError::protocol()),
                        },
                        client: None,
                    },
                }
            }
            Err(error) => Self {
                info: BridgeInfo {
                    mode: BackendMode::Real,
                    available: false,
                    error: Some(error),
                },
                client: None,
            },
        }
    }
    pub fn info(&self) -> BridgeInfo {
        self.info.clone()
    }
    pub fn client(&self) -> Result<BridgeClient, BridgeError> {
        self.client.clone().ok_or_else(BridgeError::protocol)
    }
    pub fn shutdown(&self) {
        if let Some(client) = &self.client {
            client.shutdown();
        }
    }
}
fn verify_backend_ready(client: &BridgeClient) -> Result<(), BridgeError> {
    let result = client.request("devices.list", json!({}))?;
    if result.get("devices").and_then(Value::as_array).is_some() {
        Ok(())
    } else {
        Err(BridgeError::protocol())
    }
}

impl Default for BridgeState {
    fn default() -> Self {
        Self::new()
    }
}

async fn invoke_bridge(
    client: BridgeClient,
    command: &'static str,
    payload: Value,
) -> Result<Value, BridgeError> {
    tauri::async_runtime::spawn_blocking(move || client.request(command, payload))
        .await
        .map_err(|_| BridgeError::protocol())?
}
fn valid_device_id(value: &str) -> bool {
    !value.trim().is_empty() && value.len() <= 128
}
fn valid_percent(value: f64) -> bool {
    value.is_finite() && (0.0..=100.0).contains(&value)
}
fn validate_id(value: &str) -> Result<(), BridgeError> {
    if valid_device_id(value) {
        Ok(())
    } else {
        Err(BridgeError::new(BridgeErrorCode::InvalidInput))
    }
}

#[tauri::command]
pub fn bridge_info(state: State<'_, BridgeState>) -> BridgeInfo {
    state.info()
}
#[tauri::command]
pub async fn bridge_list(state: State<'_, BridgeState>) -> Result<Value, BridgeError> {
    invoke_bridge(state.client()?, "devices.list", json!({})).await
}
#[tauri::command]
pub async fn bridge_status(
    state: State<'_, BridgeState>,
    device_id: String,
) -> Result<Value, BridgeError> {
    validate_id(&device_id)?;
    invoke_bridge(
        state.client()?,
        "device.status",
        json!({"deviceId":device_id}),
    )
    .await
}
#[tauri::command]
pub async fn bridge_power(
    state: State<'_, BridgeState>,
    device_id: String,
    enabled: bool,
) -> Result<Value, BridgeError> {
    validate_id(&device_id)?;
    invoke_bridge(
        state.client()?,
        "device.power",
        json!({"deviceId":device_id,"enabled":enabled}),
    )
    .await
}
#[tauri::command]
pub async fn bridge_white_brightness(
    state: State<'_, BridgeState>,
    device_id: String,
    percent: f64,
) -> Result<Value, BridgeError> {
    validate_id(&device_id)?;
    if !valid_percent(percent) {
        return Err(BridgeError::new(BridgeErrorCode::InvalidInput));
    }
    invoke_bridge(
        state.client()?,
        "device.whiteBrightness",
        json!({"deviceId":device_id,"percent":percent}),
    )
    .await
}
#[tauri::command]
pub async fn bridge_color_temperature(
    state: State<'_, BridgeState>,
    device_id: String,
    percent: f64,
) -> Result<Value, BridgeError> {
    validate_id(&device_id)?;
    if !valid_percent(percent) {
        return Err(BridgeError::new(BridgeErrorCode::InvalidInput));
    }
    invoke_bridge(
        state.client()?,
        "device.colorTemperature",
        json!({"deviceId":device_id,"percent":percent}),
    )
    .await
}
#[tauri::command]
pub async fn bridge_hsv(
    state: State<'_, BridgeState>,
    device_id: String,
    hue: f64,
    saturation: f64,
    value: f64,
) -> Result<Value, BridgeError> {
    validate_id(&device_id)?;
    if !hue.is_finite()
        || !(0.0..=360.0).contains(&hue)
        || !valid_percent(saturation)
        || !valid_percent(value)
    {
        return Err(BridgeError::new(BridgeErrorCode::InvalidInput));
    }
    invoke_bridge(
        state.client()?,
        "device.hsv",
        json!({"deviceId":device_id,"hue":hue,"saturation":saturation,"value":value}),
    )
    .await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;
    #[test]
    fn bounded_reader_accepts_crlf_at_limit_and_rejects_oversize() {
        let line = vec![b'a'; MAX_MESSAGE_BYTES];
        let mut input = Cursor::new([line.clone(), b"\r\n".to_vec()].concat());
        assert_eq!(
            read_bounded_line(&mut input).unwrap().unwrap().len(),
            MAX_MESSAGE_BYTES
        );
        let mut too_long = Cursor::new(vec![b'x'; MAX_MESSAGE_BYTES + 1]);
        assert!(read_bounded_line(&mut too_long).is_err());
    }
    #[test]
    fn parses_success_and_safe_errors_and_rejects_extra_envelope_fields() {
        assert_eq!(
            parse_response(br#"{"requestId":"r1","result":{"x":1}}"#)
                .unwrap()
                .0,
            "r1"
        );
        assert_eq!(
            parse_response(br#"{"requestId":"r2","error":{"code":"TIMEOUT","message":"ignored"}}"#)
                .unwrap()
                .1
                .unwrap_err()
                .code,
            BridgeErrorCode::Timeout
        );
        assert!(parse_response(br#"{"requestId":"r1","result":{},"extra":1}"#).is_err());
    }
    fn python_process(script: &str) -> Child {
        let mut command = Command::new("python");
        command
            .args(["-u", "-c", script])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        command
            .spawn()
            .expect("Python is required for local IPC fixture tests")
    }
    #[test]
    fn readiness_probe_requires_a_valid_catalog_response() {
        let valid = BridgeClient::spawn_command(python_process(
            r#"import sys; sys.stdin.readline(); print('{"requestId":"req-1","result":{"devices":[]}}', flush=True)"#,
        )).unwrap();
        assert!(verify_backend_ready(&valid).is_ok());
        valid.shutdown();

        let exited = BridgeClient::spawn_command(python_process("pass")).unwrap();
        assert_eq!(
            verify_backend_ready(&exited).unwrap_err().code,
            BridgeErrorCode::DeviceError
        );
        exited.shutdown();

        let invalid = BridgeClient::spawn_command(python_process(
            r#"import sys; sys.stdin.readline(); print('{"requestId":"req-1","result":{}}', flush=True)"#,
        )).unwrap();
        assert_eq!(
            verify_backend_ready(&invalid).unwrap_err().code,
            BridgeErrorCode::DeviceError
        );
        invalid.shutdown();
    }

    #[test]
    fn fixture_process_starts_lists_and_shuts_down_without_orphan() {
        let client = BridgeClient::spawn_config(&ProcessConfig::Fixture).expect("fixture starts");
        let result = client.request("devices.list", json!({})).unwrap();
        assert_eq!(result["devices"].as_array().unwrap().len(), 2);
        client.shutdown();
        assert!(client.child.lock().unwrap().is_none());
    }
    #[test]
    fn fixture_correlates_concurrent_out_of_order_responses() {
        let client = BridgeClient::spawn_config(&ProcessConfig::Fixture).unwrap();
        let barrier = Arc::new(std::sync::Barrier::new(2));
        let slow_client = client.clone();
        let slow_barrier = barrier.clone();
        let slow = thread::spawn(move || {
            slow_barrier.wait();
            slow_client
                .request("device.status", json!({"deviceId":"fixture-desk-lamp"}))
                .unwrap()["deviceId"]
                .clone()
        });
        let fast_client = client.clone();
        let fast_barrier = barrier.clone();
        let fast = thread::spawn(move || {
            fast_barrier.wait();
            fast_client
                .request("device.status", json!({"deviceId":"fixture-led-strip"}))
                .unwrap()["deviceId"]
                .clone()
        });
        assert_eq!(fast.join().unwrap(), "fixture-led-strip");
        assert_eq!(slow.join().unwrap(), "fixture-desk-lamp");
        client.shutdown();
    }
    #[test]
    fn timeout_eof_malformed_and_oversized_child_responses_are_safe() {
        let mut timeout =
            BridgeClient::spawn_command(python_process("import time; time.sleep(1)")).unwrap();
        timeout.timeout = Duration::from_millis(10);
        assert_eq!(
            timeout
                .request("device.status", json!({"deviceId":"x"}))
                .unwrap_err()
                .code,
            BridgeErrorCode::Timeout
        );
        timeout.shutdown();
        let eof = BridgeClient::spawn_command(python_process("pass")).unwrap();
        assert_eq!(
            eof.request("devices.list", json!({})).unwrap_err().code,
            BridgeErrorCode::DeviceError
        );
        eof.shutdown();
        let malformed =
            BridgeClient::spawn_command(python_process("print('not-json', flush=True)")).unwrap();
        assert_eq!(
            malformed
                .request("devices.list", json!({}))
                .unwrap_err()
                .code,
            BridgeErrorCode::DeviceError
        );
        malformed.shutdown();
        let oversized =
            BridgeClient::spawn_command(python_process("print('x' * 65537, flush=True)")).unwrap();
        assert_eq!(
            oversized
                .request("devices.list", json!({}))
                .unwrap_err()
                .code,
            BridgeErrorCode::InvalidInput
        );
        oversized.shutdown();
    }
    #[test]
    fn backend_error_codes_are_normalized_to_allowlist() {
        for (wire, expected) in [
            ("DEVICE_OFFLINE", BridgeErrorCode::DeviceOffline),
            ("COMMAND_CANCELED", BridgeErrorCode::CommandCanceled),
            ("TIMEOUT", BridgeErrorCode::Timeout),
            ("AUTH_FAILED", BridgeErrorCode::AuthFailed),
            ("INVALID_INPUT", BridgeErrorCode::InvalidInput),
            (
                "UNSUPPORTED_CAPABILITY",
                BridgeErrorCode::UnsupportedCapability,
            ),
            ("private-exception", BridgeErrorCode::DeviceError),
        ] {
            assert_eq!(BridgeError::from_backend(wire).code, expected);
        }
    }
    fn shared_for_test() -> Arc<Shared> {
        Arc::new(Shared {
            requests: Mutex::new(RequestState {
                pending: HashMap::new(),
                failed: None,
            }),
            next_id: AtomicU64::new(1),
        })
    }

    #[test]
    fn concurrent_failure_and_registration_always_finish_terminally() {
        for index in 0..32 {
            let shared = shared_for_test();
            let barrier = Arc::new(std::sync::Barrier::new(3));
            let (sender, receiver) = mpsc::channel();
            let registering_shared = shared.clone();
            let registering_barrier = barrier.clone();
            let registration = thread::spawn(move || {
                registering_barrier.wait();
                register_pending(&registering_shared, format!("race-{index}"), sender)
            });
            let failing_shared = shared.clone();
            let failing_barrier = barrier.clone();
            let failure = thread::spawn(move || {
                failing_barrier.wait();
                fail_shared(&failing_shared, BridgeError::protocol());
            });
            barrier.wait();
            let registered = registration.join().unwrap();
            failure.join().unwrap();
            match registered {
                Ok(()) => assert_eq!(
                    receiver
                        .recv_timeout(Duration::from_secs(1))
                        .unwrap()
                        .unwrap_err()
                        .code,
                    BridgeErrorCode::DeviceError
                ),
                Err(error) => assert_eq!(error.code, BridgeErrorCode::DeviceError),
            }
            assert!(shared.requests.lock().unwrap().pending.is_empty());
        }
    }

    #[test]
    fn backend_mode_is_mock_only_when_missing_or_explicitly_mock() {
        assert!(matches!(
            ProcessConfig::from_values(None, None, None),
            Ok(None)
        ));
        assert!(matches!(
            ProcessConfig::from_values(Some("mock"), None, None),
            Ok(None)
        ));
        assert!(matches!(
            ProcessConfig::from_values(Some("fixture"), None, None),
            Ok(Some(ProcessConfig::Fixture))
        ));
        assert!(ProcessConfig::from_values(Some("mystery"), None, None).is_err());
        assert!(ProcessConfig::from_values(Some("real"), None, None).is_err());
        assert!(ProcessConfig::from_values(Some("real"), Some("1"), None).is_err());
        let path =
            std::env::temp_dir().join(format!("smart-home-tray-test-{}.toml", std::process::id()));
        std::fs::write(&path, b"fixture = true").unwrap();
        assert!(
            matches!(ProcessConfig::from_values(Some("real"), Some("1"), Some(path.clone())), Ok(Some(ProcessConfig::Real(value))) if value == path)
        );
        let _ = std::fs::remove_file(&path);
        assert!(ProcessConfig::from_values(Some("real"), Some("1"), Some(path)).is_err());
    }
}
