import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import LoginPage from './pages/LoginPage'
import ClipsPage from './pages/ClipsPage'
import StatsPage from './pages/StatsPage'

export default function App() {
  const { token } = useAuth()

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={token ? <ClipsPage /> : <Navigate to="/login" replace />} />
      <Route path="/stats" element={token ? <StatsPage /> : <Navigate to="/login" replace />} />
      <Route path="*" element={<Navigate to={token ? '/' : '/login'} replace />} />
    </Routes>
  )
}
