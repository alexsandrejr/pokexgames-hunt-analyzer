// Mensagem da barra de status, como o statusBar do Python: some sozinha depois de 8 s.

export const status = $state({ text: "" });

let timer: ReturnType<typeof setTimeout> | undefined;

export function announce(text: string) {
  status.text = text;
  clearTimeout(timer);
  timer = setTimeout(() => (status.text = ""), 8000);
}
