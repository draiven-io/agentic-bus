# Interfaces Líquidas — UFSCar

Talk deck for the Semana da Computação at UFSCar (2026), in Portuguese:
Bauman's liquid modernity as background, the LIP protocol, IBAC governance,
and a live demo of this runtime. 22 slides, speaker notes included.

Imported from the claude.ai Slides artifact
<https://claude.ai/artifact/XFEG2Qb7u56mtP49tgSaCe> (version `1791244790-2736`)
so it can be versioned and edited alongside the code it presents.

## Layout

```
project/deck.json          index: title, slide order, sections, fonts
project/slides/<id>.html   one <section> per slide; <aside> = speaker notes
assets/<blob-id>.<ext>     images the slides reference as /_blob/<blob-id>
build_preview.py           assembles deck.html for a local preview
```

`project/` is kept byte-for-byte in the Slides artifact format, so it can be
published back to the artifact unchanged. Slides follow that format's rules:
a fixed 1920×1080 canvas, inline styles only, and images referenced as
`/_blob/<id>`. A new image therefore has to be uploaded to the artifact to get
its blob id; save a copy under `assets/` with that id as the file name.

## Preview

```bash
python docs/presentation/build_preview.py   # writes docs/presentation/deck.html (gitignored)
```

Open `deck.html` in a browser: every slide is scaled to the window, with its
speaker notes underneath. `<x-icon>` and `<x-connector>` only render properly
in the Slides runtime; the preview draws simple stand-ins for them.

## Open placeholders

Still to fill in before the talk:

- `contato`: role, e-mail, LinkedIn, the QR code image, and the jobs line.
- `quem-sou` (speaker notes): role and a one-line background.
