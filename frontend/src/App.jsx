// frontend/src/App.jsx
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { useState } from 'react'
import { Home, Calendar, Search, BarChart2, Menu, X } from 'lucide-react'
import HomePage from './pages/HomePage'
import FixturesPage from './pages/FixturesPage'
import PredictionPage from './pages/PredictionPage'
import SearchPage from './pages/SearchPage'
import AccuracyPage from './pages/AccuracyPage'

function NavItem({ to, icon: Icon, label, end }) {
  return (
    <NavLink to={to} end={end}
      className={({ isActive }) =>
        `flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
          isActive ? 'bg-emerald-600 text-white' : 'text-slate-300 hover:text-white hover:bg-slate-700'
        }`}
    >
      <Icon size={15} />{label}
    </NavLink>
  )
}

export default function App() {
  const [open, setOpen] = useState(false)
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-slate-900 text-white">
        <nav className="sticky top-0 z-50 bg-slate-800 border-b border-slate-700">
          <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
            <NavLink to="/" className="flex items-center gap-2 font-bold text-lg">
              <span className="text-2xl">⚽</span>
              <span className="text-emerald-400">StatPredict</span>
            </NavLink>
            <div className="hidden md:flex items-center gap-1">
              <NavItem to="/" icon={Home} label="Home" end />
              <NavItem to="/fixtures" icon={Calendar} label="Fixtures" />
              <NavItem to="/search" icon={Search} label="Search" />
              <NavItem to="/accuracy" icon={BarChart2} label="Track Record" />
            </div>
            <button className="md:hidden p-2 text-slate-400" onClick={() => setOpen(!open)}>
              {open ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>
          {open && (
            <div className="md:hidden border-t border-slate-700 px-4 py-3 flex flex-col gap-1">
              <NavItem to="/" icon={Home} label="Home" end />
              <NavItem to="/fixtures" icon={Calendar} label="Fixtures" />
              <NavItem to="/search" icon={Search} label="Search" />
              <NavItem to="/accuracy" icon={BarChart2} label="Track Record" />
            </div>
          )}
        </nav>
        <main className="max-w-6xl mx-auto px-4 py-6">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/fixtures" element={<FixturesPage />} />
            <Route path="/fixture/:id" element={<PredictionPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/accuracy" element={<AccuracyPage />} />
          </Routes>
        </main>
        <footer className="mt-16 border-t border-slate-700 py-6 text-center text-slate-500 text-xs">
          <p>StatPredict — Statistical football prediction engine powered by Dixon-Coles &amp; ML</p>
          <p className="mt-1">Predictions are statistical estimates only. Always bet responsibly.</p>
        </footer>
      </div>
    </BrowserRouter>
  )
}
