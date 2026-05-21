const deck = document.querySelector("#deck");
const slides = Array.from(document.querySelectorAll(".slide"));
const progressBar = document.querySelector("#progress-bar");
const currentSlideEl = document.querySelector("#current-slide");
const totalSlidesEl = document.querySelector("#total-slides");
const canvas = document.querySelector("#particle-canvas");
const ctx = canvas.getContext("2d");
const rootStyle = document.documentElement.style;

let current = 0;
let locked = false;
let particles = [];
let bgmUnlocked = false;

const INTRO_BGM_DELAY_MS = 15000;
const deckBgm = document.querySelector("#deck-bgm");
const introSlideIndex = slides.findIndex((slide) => slide.classList.contains("intro-video-slide"));

if (deckBgm) {
  deckBgm.volume = 0.28;
}

totalSlidesEl.textContent = String(slides.length).padStart(2, "0");

function setStaggerOrders() {
  slides.forEach((slide) => {
    slide.querySelectorAll(".stagger").forEach((el, index) => {
      el.style.setProperty("--order", index);
    });
  });
}

function updateDeck(index) {
  const next = Math.max(0, Math.min(slides.length - 1, index));
  current = next;
  deck.style.transform = `translate3d(0, -${current * 100}vh, 0)`;
  rootStyle.setProperty("--slide-depth", `${current * 20}px`);
  slides.forEach((slide, slideIndex) => slide.classList.toggle("is-active", slideIndex === current));
  currentSlideEl.textContent = String(current + 1).padStart(2, "0");
  progressBar.style.width = `${((current + 1) / slides.length) * 100}%`;
  handleSlideMedia(slides[current]);
  syncDeckBgm();
  runSlideAnimations(slides[current]);
}

function isIntroSlide(index = current) {
  return index === introSlideIndex;
}

function syncDeckBgm() {
  if (!deckBgm || !bgmUnlocked) return;

  if (isIntroSlide()) {
    deckBgm.pause();
    return;
  }

  const playPromise = deckBgm.play();
  if (playPromise) playPromise.catch(() => {});
}

function initDeckBgm() {
  window.setTimeout(() => {
    bgmUnlocked = true;
    syncDeckBgm();
  }, INTRO_BGM_DELAY_MS);
}

function go(delta) {
  if (locked) return;
  locked = true;
  updateDeck(current + delta);
  window.setTimeout(() => {
    locked = false;
  }, 860);
}

function runSlideAnimations(slide) {
  slide.querySelectorAll(".bar, .revenue-bar").forEach((bar) => {
    const height = bar.dataset.height || 50;
    bar.style.setProperty("--bar-height", `${height}%`);
  });

  slide.querySelectorAll(".funds-row").forEach((row) => {
    const height = row.dataset.height || 50;
    row.style.setProperty("--bar-height", `${height}%`);
  });

  slide.querySelectorAll(".chart-line").forEach((line) => {
    const length = Math.ceil(line.getTotalLength());
    line.style.setProperty("--line-length", length);
    line.style.animation = "none";
    line.getBoundingClientRect();
    line.style.animation = "";
  });

  slide.querySelectorAll(".count").forEach((el) => countUp(el));
  slide.querySelectorAll("[data-type-text]").forEach((el) => typeText(el));
}

function countUp(el) {
  const target = Number(el.dataset.target || 0);
  const duration = 1150;
  const startTime = performance.now();

  function tick(now) {
    const progress = Math.min(1, (now - startTime) / duration);
    const eased = 1 - Math.pow(1 - progress, 4);
    el.textContent = Math.round(target * eased).toLocaleString("en-US");
    if (progress < 1) requestAnimationFrame(tick);
  }

  requestAnimationFrame(tick);
}

function handleKeyboard(event) {
  const keys = ["ArrowDown", "ArrowRight", "PageDown", " "];
  const reverseKeys = ["ArrowUp", "ArrowLeft", "PageUp"];
  if (keys.includes(event.key)) {
    event.preventDefault();
    go(1);
  }
  if (reverseKeys.includes(event.key)) {
    event.preventDefault();
    go(-1);
  }
  if (event.key === "Home") updateDeck(0);
  if (event.key === "End") updateDeck(slides.length - 1);
}

function handleWheel(event) {
  if (Math.abs(event.deltaY) < 18) return;
  go(event.deltaY > 0 ? 1 : -1);
}

function bindMouseGlow() {
  document.querySelectorAll(".glass-card").forEach((card) => {
    card.addEventListener("pointermove", (event) => {
      const rect = card.getBoundingClientRect();
      const mx = ((event.clientX - rect.left) / rect.width) * 100;
      const my = ((event.clientY - rect.top) / rect.height) * 100;
      card.style.setProperty("--mx", `${mx}%`);
      card.style.setProperty("--my", `${my}%`);
    });
  });
}

function bindPointerAtmosphere() {
  window.addEventListener("mousemove", (event) => {
    const x = event.clientX;
    const y = event.clientY;
    const px = (x / window.innerWidth - 0.5) * 24;
    const py = (y / window.innerHeight - 0.5) * 24;

    rootStyle.setProperty("--mouse-x", `${x}px`);
    rootStyle.setProperty("--mouse-y", `${y}px`);
    rootStyle.setProperty("--parallax-x", `${px}px`);
    rootStyle.setProperty("--parallax-y", `${py}px`);
  });
}

function bindButtons() {
  document.querySelectorAll("[data-next]").forEach((button) => {
    button.addEventListener("click", () => go(1));
  });
}

function bindEditableImages() {
  document.querySelectorAll(".editable-image").forEach((image) => {
    image.addEventListener("click", () => {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = "image/*";
      input.addEventListener("change", () => {
        const file = input.files?.[0];
        if (!file) return;

        const reader = new FileReader();
        reader.addEventListener("load", () => {
          image.src = reader.result;
        });
        reader.readAsDataURL(file);
      });
      input.click();
    });
  });
}

function handleSlideMedia(activeSlide) {
  slides.forEach((slide) => {
    slide.querySelectorAll("video").forEach((video) => {
      if (slide === activeSlide) {
        video.currentTime = video.dataset.replay === "false" ? video.currentTime : 0;
        video.play().catch(() => {});
      } else {
        video.pause();
      }
    });
  });
}

function bindIntroVideo() {
  document.querySelectorAll("video[data-auto-next]").forEach((video) => {
    video.addEventListener("ended", () => {
      if (slides[current]?.contains(video)) go(1);
    });
  });
}

function typeText(el) {
  const text = el.dataset.typeText || el.textContent;
  const duration = 900;
  const startTime = performance.now();
  el.classList.add("is-typing");
  el.textContent = "";

  function tick(now) {
    const progress = Math.min(1, (now - startTime) / duration);
    const visibleChars = Math.max(1, Math.floor(text.length * progress));
    el.textContent = text.slice(0, visibleChars);

    if (progress < 1) {
      requestAnimationFrame(tick);
    } else {
      el.textContent = text;
      window.setTimeout(() => el.classList.remove("is-typing"), 260);
    }
  }

  requestAnimationFrame(tick);
}

function resizeCanvas() {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.floor(window.innerWidth * dpr);
  canvas.height = Math.floor(window.innerHeight * dpr);
  canvas.style.width = `${window.innerWidth}px`;
  canvas.style.height = `${window.innerHeight}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const count = Math.max(42, Math.floor((window.innerWidth * window.innerHeight) / 28000));
  particles = Array.from({ length: count }, () => createParticle());
}

function createParticle() {
  return {
    x: Math.random() * window.innerWidth,
    y: Math.random() * window.innerHeight,
    vx: (Math.random() - 0.5) * 0.18,
    vy: (Math.random() - 0.5) * 0.18,
    r: Math.random() * 1.8 + 0.5,
    hue: Math.random() > 0.58 ? "244, 244, 245" : "113, 113, 122"
  };
}

function drawParticles() {
  ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);

  particles.forEach((particle, index) => {
    particle.x += particle.vx;
    particle.y += particle.vy;

    if (particle.x < -20) particle.x = window.innerWidth + 20;
    if (particle.x > window.innerWidth + 20) particle.x = -20;
    if (particle.y < -20) particle.y = window.innerHeight + 20;
    if (particle.y > window.innerHeight + 20) particle.y = -20;

    ctx.beginPath();
    ctx.fillStyle = `rgba(${particle.hue}, 0.55)`;
    ctx.arc(particle.x, particle.y, particle.r, 0, Math.PI * 2);
    ctx.fill();

    for (let j = index + 1; j < particles.length; j += 1) {
      const other = particles[j];
      const dx = particle.x - other.x;
      const dy = particle.y - other.y;
      const distance = Math.hypot(dx, dy);
      if (distance < 145) {
        ctx.beginPath();
        ctx.strokeStyle = `rgba(212, 212, 216, ${0.1 * (1 - distance / 145)})`;
        ctx.lineWidth = 1;
        ctx.moveTo(particle.x, particle.y);
        ctx.lineTo(other.x, other.y);
        ctx.stroke();
      }
    }
  });

  requestAnimationFrame(drawParticles);
}

setStaggerOrders();
bindMouseGlow();
bindPointerAtmosphere();
bindButtons();
bindEditableImages();
bindIntroVideo();
initDeckBgm();
resizeCanvas();
drawParticles();
updateDeck(0);

window.addEventListener("keydown", handleKeyboard);
window.addEventListener("wheel", handleWheel, { passive: true });
window.addEventListener("resize", resizeCanvas);
