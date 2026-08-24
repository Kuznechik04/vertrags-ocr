import { Link, Route, Routes } from "react-router-dom";
import DocumentListPage from "./components/DocumentListPage";
import DocumentReviewPage from "./components/DocumentReviewPage";
import LoginPage from "./components/LoginPage";
import RegisterPage from "./components/RegisterPage";
import TemplateAdminPage from "./components/TemplateAdminPage";
import RequireAuth from "./auth/RequireAuth";
import { useAuth } from "./auth/AuthContext";

export default function App() {
  const { user, logout } = useAuth();

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header-row">
          <div>
            <h1>Vertrags-OCR Review</h1>
            <p>Verträge hochladen, erkannte Felder prüfen und korrigieren.</p>
          </div>
          {user && (
            <div className="user-badge">
              <span>
                {user.email} {user.role === "admin" && <span className="admin-tag">Admin</span>}
              </span>
              {user.role === "admin" && <Link to="/admin/templates">Vertragstypen</Link>}
              <button className="link-btn" onClick={logout}>
                Abmelden
              </button>
            </div>
          )}
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <DocumentListPage />
              </RequireAuth>
            }
          />
          <Route
            path="/documents/:id"
            element={
              <RequireAuth>
                <DocumentReviewPage />
              </RequireAuth>
            }
          />
          <Route
            path="/admin/templates"
            element={
              <RequireAuth>
                <TemplateAdminPage />
              </RequireAuth>
            }
          />
          <Route path="*" element={<Link to="/">Zurück zur Startseite</Link>} />
        </Routes>
      </main>
    </div>
  );
}
