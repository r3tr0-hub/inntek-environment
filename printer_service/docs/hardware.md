# Hardware

Which printer to buy and where to find one. This page is about the cheap **"420B"-class** 4×6
direct-thermal label printers LabelJetty targets.

> ⚠️ **This is a stub based on a quick LLM web search - your mileage may vary.** Models, brands,
> and regional availability change constantly, and the same hardware is rebadged under many names.
> Treat everything below as a starting point, not verified buying advice. (A more thorough,
> hand-checked version is planned.)

## What to look for

LabelJetty needs a **USB label printer that speaks TSPL** (~203 dpi is typical). The reference
device is a **Vretti 420B** (USB id `2d37:62de`), which is a Zhuhai **Poskey**-class OEM - the
same internals are sold under many brand names. Any printer that genuinely accepts TSPL over USB
*should* work; only the Vretti 420B is verified so far. If you try another model, please report
back in an [issue](../../issues) - that's how the supported list grows.

Notes from the quick search:

- The "420B" is a generic 4×6 (≈101×152 mm) direct-thermal shipping-label form factor sold by
  many vendors at 203 dpi. Common brands include **Vretti**, **Xprinter (XP-420B)**, **MUNBYN**,
  **Phomemo**, **Rollo**, and assorted unbranded AliExpress units.
- Many of these are the same OEM hardware, so USB ids and TSPL behaviour can match even across
  brands. Prefer a **USB** variant (Bluetooth/Wi-Fi-only models are not what LabelJetty drives).
- Cheap clones are often **write-only for status** - they print fine but never answer status
  queries (see [Configuration → Status reading is optional](configuration.md#status-reading-is-optional)).

## Rough regional availability

Very rough, unverified pointers:

| Region | Where people tend to find them |
| --- | --- |
| North America | Amazon US, eBay, Walmart, Newegg; brands like Vretti, MUNBYN, Rollo, Phomemo |
| Europe | Amazon (DE/FR/UK/...), brands like Phomemo, MUNBYN, Aibecy, plus Vretti's EU store |
| Asia / global | AliExpress (Xprinter XP-420B and generic 420B units), Taobao |
| Oceania | Amazon AU, eBay AU (e.g. MUNBYN AU) |

## Sources

- [VRETTI 420B (official)](https://vrettitech.com/products/thermal-printer-420b-usb)
- [Xprinter XP-420B](https://www.xprintertech.com/xp-420b-thermal-label-printer.html)
- [MUNBYN thermal label printers](https://munbyn.com/collections/thermal-label-printer)
- [Phomemo shipping label printers](https://phomemo.com/collections/shipping-label-printer)
