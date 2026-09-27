# `<img>` smoke pages

Copy these to `/root/cr153/smoke/` on core, then run from `/root/cr153`:
`bash smoke/hy.sh "img.html?block=3000" 9 img` (put `FLAG=` in front for stock Chrome), and
`python3 smoke/imgan.py smoke/hy-img.mkv` to print where each colored image is drawn over time.

- `img.html`: src, srcset 2x and an image added after load, inside a panel that animates during a 3 s busy loop.
- `img2.html`: EXIF-rotated JPEG, `<picture>`, a large downscaled JPEG and a src changed by script. Make `big.jpg` with any
  2400x1600 JPEG.
- `imgbad.html`, `imggif.html`: broken and animated images. The page must opt out ("cannot reproduce this page").

Result on the `<img>` build: while the render thread draws, the images match stock Chrome to within 3/255 per channel.
