import { mount } from "svelte";
import App from "./App.svelte";
import InstallView from "./InstallView.svelte";
import "./app.css";
import { installDiagnostics } from "./lib/diagnostics";

// "#install": janela de progresso da atualização (`--apply-update`); o resto é o programa.
const view = window.location.hash === "#install" ? InstallView : App;
installDiagnostics();
mount(view, { target: document.getElementById("app")! });
