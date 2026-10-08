import { useEffect } from "react";

export default function Login() {
  useEffect(() => {
    window.location.replace("/auth/login");
  }, []);
  return <p>Переходим ко входу через Authentik…</p>;
}
