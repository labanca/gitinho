export default function LoginScreen() {
  const params = new URLSearchParams(window.location.search);
  const error = params.get("error");
  const org = params.get("org");
  return (
    <div className="login-screen">
      <div className="login-card">
        <h1>Gitinho</h1>
        <p>Agente conversacional para sua organização do GitHub.</p>
        {error === "forbidden" && (
          <div className="login-error">
            Você precisa ser membro da organização{" "}
            <strong>{org}</strong> para acessar.
          </div>
        )}
        {error === "oauth" && (
          <div className="login-error">
            Não foi possível concluir o login. Tente novamente.
          </div>
        )}
        <a className="btn-primary" href="/auth/github/login">
          Entrar com GitHub
        </a>
      </div>
    </div>
  );
}
