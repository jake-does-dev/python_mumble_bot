import { createContext, useContext, useState } from 'react'
import axios from 'axios'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem('token'))

  async function login(username, password) {
    const params = new URLSearchParams()
    params.append('username', username)
    params.append('password', password)
    const res = await axios.post('/api/users/login', params)
    localStorage.setItem('token', res.data.access_token)
    setToken(res.data.access_token)
  }

  function logout() {
    localStorage.removeItem('token')
    setToken(null)
  }

  return (
    <AuthContext.Provider value={{ token, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
