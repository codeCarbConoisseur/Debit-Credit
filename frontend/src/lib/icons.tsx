import {
  Banknote,
  Bitcoin,
  Briefcase,
  Building2,
  Car,
  Clapperboard,
  Code,
  Dumbbell,
  Gamepad2,
  Gem,
  Gift,
  GraduationCap,
  HandCoins,
  HeartPulse,
  Home,
  Key,
  MoreHorizontal,
  Package,
  PiggyBank,
  Plane,
  PlusCircle,
  Receipt,
  Repeat,
  Shapes,
  Shirt,
  ShoppingBag,
  ShoppingBasket,
  Smartphone,
  Sofa,
  Sparkles,
  Tag,
  TrendingUp,
  Truck,
  Utensils,
  Video,
  Wallet,
  ZapOff,
  type LucideIcon,
} from "lucide-react";

// Maps the backend's plain-string icon keys (Category.icon) to a concrete
// lucide component. New categories fall back to a generic wallet glyph so an
// unmapped icon key never breaks rendering. Keep this in sync with whatever
// icon keys actually exist on Category rows — an icon used by a real
// category but missing here silently renders as the Wallet fallback.
const ICON_MAP: Record<string, LucideIcon> = {
  home: Home,
  "shopping-basket": ShoppingBasket,
  utensils: Utensils,
  car: Car,
  "heart-pulse": HeartPulse,
  "shopping-bag": ShoppingBag,
  clapperboard: Clapperboard,
  repeat: Repeat,
  banknote: Banknote,
  briefcase: Briefcase,
  "trending-up": TrendingUp,
  gift: Gift,
  "plus-circle": PlusCircle,
  "more-horizontal": MoreHorizontal,
  wallet: Wallet,
  "piggy-bank": PiggyBank,
  bitcoin: Bitcoin,
  "building-2": Building2,
  package: Package,
  gem: Gem,
  code: Code,
  dumbbell: Dumbbell,
  "gamepad-2": Gamepad2,
  "graduation-cap": GraduationCap,
  plane: Plane,
  receipt: Receipt,
  shapes: Shapes,
  shirt: Shirt,
  smartphone: Smartphone,
  sofa: Sofa,
  sparkles: Sparkles,
  tag: Tag,
  "hand-coins": HandCoins,
  key: Key,
  truck: Truck,
  // lucide-react dropped brand/trademarked glyphs (no "Youtube" icon) — a
  // generic video-camera icon is the closest available stand-in.
  youtube: Video,
  "zap-off": ZapOff,
};

export function getCategoryIcon(icon: string | null | undefined): LucideIcon {
  if (!icon) return Wallet;
  return ICON_MAP[icon] ?? Wallet;
}

// The full set of icon keys a category can be assigned, for the icon picker
// in the category form — kept in sync with ICON_MAP above.
export const CATEGORY_ICON_OPTIONS = Object.keys(ICON_MAP);
