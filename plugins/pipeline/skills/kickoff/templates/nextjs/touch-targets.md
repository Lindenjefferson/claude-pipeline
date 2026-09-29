# 44px touch targets for shadcn primitives

Apply only when the project is mobile-first (style guide or spec says so; ask if unsure). Pattern: 44px (`h-11` / `size-11`) below `md`, the shadcn default from `md` up, so desktop density is unchanged. Edit the generated files in `components/ui/` right after `shadcn add`, and again for every primitive added later.

| Primitive | File | Change |
|---|---|---|
| Button sizes | `button.tsx` (`size` variants) | `default: h-8` → `h-11 md:h-8`; `xs: h-6` → `h-11 md:h-6`; `sm: h-7` → `h-11 md:h-7`; `lg: h-9` → `h-11 md:h-9`; `icon: size-8` → `size-11 md:size-8`; same for `icon-xs` / `icon-sm` / `icon-lg` |
| Input | `input.tsx` | `h-8` → `h-11 md:h-8` (keep `text-base md:text-sm`: iOS zooms inputs under 16px) |
| Select trigger | `select.tsx` (`SelectTrigger`) | `data-[size=default]:h-8` → `data-[size=default]:h-11 md:data-[size=default]:h-8`; `data-[size=sm]:h-7` → `data-[size=sm]:h-11 md:data-[size=sm]:h-7` |
| Select item | `select.tsx` (`SelectItem`) | add `min-h-11 md:min-h-0` |
| Radio item | `radio-group.tsx` (`RadioGroupItem`) | keep the 16px circle; enlarge the hit area with `after:absolute after:-inset-3.5 md:after:-inset-2` (16 + 2·14 = 44) and give the group `gap-3` so hit areas do not overlap |
| Checkbox, switch, dropdown/menu items, tabs triggers | their files | same idea: `min-h-11 md:min-h-<default>` for rows, invisible `after:` hit area for small controls |

Verify at 360px wide (browser devtools) that each control's box is at least 44×44.
