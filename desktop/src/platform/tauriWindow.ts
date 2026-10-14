import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'

export function isTauriRuntime(): boolean {
  return isTauri()
}

export async function hidePanel(): Promise<boolean> {
  if (!isTauriRuntime()) return false
  try {
    await getCurrentWindow().hide()
    return true
  } catch {
    return false
  }
}

export async function startDraggingPanel(target: EventTarget | null, button: number): Promise<boolean> {
  if (button !== 0 || isInteractiveTarget(target) || !isTauriRuntime()) return false
  try {
    await getCurrentWindow().startDragging()
    return true
  } catch {
    return false
  }
}

function isInteractiveTarget(target: EventTarget | null): boolean {
  if (typeof Element === 'undefined' || !(target instanceof Element)) return false
  return target.closest('button, a, input, select, textarea, [role="button"], [contenteditable="true"]') !== null
}
