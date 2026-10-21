import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './app/LightingApp'
import { ApplicationSessionHost } from './app/ApplicationSessionHost'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ApplicationSessionHost><App /></ApplicationSessionHost>
  </StrictMode>,
)
