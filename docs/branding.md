<!-- Copyright 2026 Firefly Software Foundation. SPDX-License-Identifier: Apache-2.0 -->

# flyquery identity and repository

The canonical source repository is [flyquery](https://github.com/fireflyframework/flyquery).
Clone it from that address and use its Issues and Releases pages for support and
published packages. Existing release tags and downloadable files retain their
versions and checksums.

## Banners

The README has separate desktop and mobile banners for light and dark themes.
They use outlined Manrope lettering, the official Firefly wordmark and the
Framework brandkit palette: charcoal `#10110f`, paper `#f3f1eb` and amber
`#ffb34a`. The final `y` carries the original Firefly amber light trail, following the
framework-family wordmarks. The Manrope glyph and its spacing remain intact.
Reusable light and dark logos accompany the banners. Each banner contains its
own title and description and loads no fonts, JavaScript or external resources.

The illustration follows a highlighted table through a SQL query to a result
chart. The SQL panel makes the query step visible between the data and its
result.
It represents the service's purpose; it is not a live status display.

Artwork was produced from the [Framework brandkit](https://github.com/fireflyframework/brand-kit)
at `b64a50e289b853cab54e5d59bc1b092b48c5eec4`, using Manrope 5.3.0 and the
unchanged parent geometry in `vendor/firefly/scripts/logo.mjs`. Font outlines
come from `scripts/type.mjs`; the source assets are under `assets/brand/`.

Manrope is licensed under the SIL Open Font License 1.1. No font files are
redistributed here. The Firefly name and marks remain trademarks of Firefly
Software Solutions Inc.; this repository's Apache 2.0 software license does not
grant trademark rights. Keep that distinction when reusing the artwork.

## Package registries

GitHub source and release-download URLs use `fireflyframework/flyquery`. Future
Java SDK publications target `maven.pkg.github.com/fireflyframework/flyquery`.
The container workflow derives the namespace from the current repository owner,
so future images target `ghcr.io/fireflyframework/flyquery`.

Historical container examples retain `ghcr.io/firefly-operationos/flyquery`.
A repository transfer does not prove that an image or Maven package exists in
the new namespace. Check the published package inventory and select an explicit
version or digest before installation; do not infer registry availability from
a working GitHub source link.
