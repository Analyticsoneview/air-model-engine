# AIR mobile UI design system

## Product direction
- Brand: Analytical Investment Research (AIR).
- Positioning: premium institutional investment intelligence.
- Audience: retail and HNI/professional users on one platform.
- Default appearance: premium dark; optional premium light.
- Tagline: Intelligence. Precision. Control.
- The app remains a research and broker-connectivity client; UI work must not enable broker order placement.

## Shared design tokens
The source of truth is `lib/theme/air_theme.dart`.
- Dark background: `#101827`; surface: `#182438`; elevated surface: `#202E42`.
- Light background: `#F4F6FA`; surface: `#FFFFFF`.
- Dark brand accent: `#D6AA52`; light brand accent: `#A97B25`.
- Positive: `#16A37B`; negative: `#E05252`; warning: `#E7A83E`.
- Spacing uses a 4 px base unit; cards use 16 px radius; controls use 12 px radius.
- Theme selection is persisted locally using the existing secure-storage dependency. Dark remains the fallback if storage is unavailable.

## Navigation
- Five primary destinations: Home, Intelligence, Markets, AIR QOC and More.
- Phones use a bottom navigation bar.
- Widths of 900 px and above use a navigation rail.
- Widths of 1200 px and above use the extended rail.
- Existing ORB, NSE Data, AIR Admin and Broker Connections screens remain accessible under More.
- Existing screens and API integrations are retained; no placeholder is presented as live market data.

## Implementation rules
- Build screens from the shared Material theme and reusable components.
- Keep backend and strategy calculations out of presentation widgets.
- Display feed state and freshness honestly; never style missing data as a valid quote.
- Use semantic positive/negative/error colours in addition to text labels or icons.
- Keep manual execution as the default; do not introduce order placement in this UI foundation.
- Preserve the current Flutter, FastAPI, broker, PWA and self-hosted deployment boundaries.

## Validation
The Android/PWA workflows run `flutter analyze lib` and `flutter test`.
New theme tests verify dark/light palette consistency and semantic trading colours.
