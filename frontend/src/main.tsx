import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './index.css'
import ChatPage from './customer/ChatPage'
import CasesPage from './staff/CasesPage'
import DocumentsPage from './staff/DocumentsPage'
import EvaluationPage from './staff/EvaluationPage'
import LoginPage from './staff/LoginPage'
import OverviewPage from './staff/OverviewPage'
import SettingsPage from './staff/SettingsPage'
import StaffLayout from './staff/StaffLayout'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ChatPage />} />
        <Route path="/staff/login" element={<LoginPage />} />
        <Route path="/staff" element={<StaffLayout />}>
          <Route index element={<OverviewPage />} />
          <Route path="cases" element={<CasesPage />} />
          <Route path="documents" element={<DocumentsPage />} />
          <Route path="evaluation" element={<EvaluationPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
