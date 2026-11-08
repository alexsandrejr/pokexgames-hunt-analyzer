// Roda um trecho de JavaScript na janela do app em desenvolvimento, sem mexer no mouse.
// O app precisa ter sido aberto com WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333.
// Uso: node rust/tools/cdp.mjs "document.title"   (o resultado, se houver, sai no terminal)

const port = process.env.CDP_PORT ?? "9333";
const expression = process.argv[2];
if (!expression) {
  console.error("Informe o JavaScript a rodar.");
  process.exit(2);
}

const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const page = targets.find((t) => t.type === "page");
if (!page) {
  console.error("Nenhuma página encontrada na porta de depuração.");
  process.exit(1);
}

const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve) => socket.addEventListener("open", resolve));
socket.send(
  JSON.stringify({
    id: 1,
    method: "Runtime.evaluate",
    params: { expression, awaitPromise: true, returnByValue: true },
  }),
);
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.id !== 1) return;
  const { result, exceptionDetails } = message.result;
  if (exceptionDetails) {
    console.error(exceptionDetails.exception?.description ?? exceptionDetails.text);
    process.exitCode = 1;
  } else if (result.value !== undefined) {
    console.log(typeof result.value === "string" ? result.value : JSON.stringify(result.value, null, 2));
  }
  socket.close();
});
