/** "steer_left" becomes "Steer left"; "drive1_right_inner" becomes "Drive1 right inner". */
export function positionLabel(position: string | null | undefined): string {
  if (!position) return "";
  const words = position.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
