const COPY_EMAIL_SELECTOR = "[data-copy-email]";

async function copyText(value) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const input = document.createElement("textarea");
  input.value = value;
  input.setAttribute("readonly", "");
  input.style.position = "fixed";
  input.style.opacity = "0";
  input.style.pointerEvents = "none";
  document.body.appendChild(input);
  input.select();
  input.setSelectionRange(0, input.value.length);

  const copied = document.execCommand("copy");
  input.remove();

  if (!copied) throw new Error("Clipboard copy failed");
}

document.addEventListener("click", async (event) => {
  const target = event.target.closest(COPY_EMAIL_SELECTOR);
  if (!target) return;

  event.preventDefault();

  const email = target.dataset.copyEmail;
  if (!email) return;

  const originalText = target.textContent;
  const originalLabel = target.getAttribute("aria-label");

  try {
    await copyText(email);
    target.textContent = "이메일 복사됨";
    target.setAttribute("aria-label", "이메일 주소가 복사되었습니다");
    target.classList.add("is-copied");

    window.setTimeout(() => {
      target.textContent = originalText;
      if (originalLabel) target.setAttribute("aria-label", originalLabel);
      else target.removeAttribute("aria-label");
      target.classList.remove("is-copied");
    }, 1400);
  } catch (error) {
    console.error("이메일 주소를 복사하지 못했습니다.", error);
  }
});
