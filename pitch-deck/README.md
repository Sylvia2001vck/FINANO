# FINANO Pitch Deck

Interactive HTML presentation for the FINANO business plan (full-screen slides, demos, and BGM).

## Quick Start

1. Clone or download this repository.
2. Open **`index.html`** in Chrome or Edge (double-click works after clone).
3. Navigate with **arrow keys**, **mouse wheel**, or **Space**.
4. Skip the 15s intro with **Skip Intro** on the first slide.
5. Background music starts after 15 seconds on formal slides (may require one click/keypress due to browser autoplay rules).
6. Press **F11** for fullscreen presentation.

## Repository Layout

```
finano-pitch-deck/
├── index.html          # Entry point
├── finano-deck.css
├── finano-deck.js
└── assets/             # Images, intro video, BGM (Git LFS)
```

## Large Files (Git LFS)

| File | ~Size |
|------|-------|
| `assets/finano_concept.mp4` | 16 MB (re-encode recommended for smooth play) |
| `assets/finano.mp3` | 25 MB |

### Intro video stutters?

1. **Page fix (already applied):** no CSS `filter` / `backdrop-filter` on the intro `<video>` (they force GPU work every frame).
2. **Re-encode for web** (best): from repo root on a machine with ffmpeg:

```bash
bash scripts/optimize-intro-video.sh
git add pitch-deck/assets/finano_concept.mp4
git push origin main
```

Target ~2–5 MB, 720p, H.264 **faststart** (starts playing before full download). Original kept as `finano_concept.source.mp4`.

Clone with LFS:

```bash
git lfs install
git clone <repo-url>
```

## Live demo (Tencent Cloud)

After CI/CD is configured: **http://43.129.199.236:8082/**

Push to `main` on [FINANOPITCHPPT](https://github.com/Sylvia2001vck/FINANOPITCHPPT) auto-deploys via GitHub Actions. See [DEPLOY.md](./DEPLOY.md) for secrets and Nginx setup.

## Links in Deck

- Product demo: http://43.129.199.236:8081
- GitHub (product code): https://github.com/Sylvia2001vck/FINANO

## License

Educational / pitch use. Open-source product code lives in the FINANO repository above.
