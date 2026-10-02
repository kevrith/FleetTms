// Colour carries meaning: red = alert, amber = warning, green = fine (always pair with text/icon).
export const colors = {
  alert: "#d92d20",
  warning: "#f79009",
  ok: "#12b76a",
  brand: "#1d4ed8",
  light: { bg: "#ffffff", surface: "#f5f7fa", text: "#101828", muted: "#667085" },
  dark: { bg: "#0b1220", surface: "#151f33", text: "#f2f4f7", muted: "#98a2b3" },
} as const;

export const spacing = { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 } as const;
export const typography = { base: 16, large: 20, title: 28, driverBig: 32 } as const;
export const tapTarget = 56;
