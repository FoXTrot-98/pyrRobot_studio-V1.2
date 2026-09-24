export function formatTimecode(epochNs: number, rateHz = 30): string {
  const totalSeconds = epochNs / 1e9;
  const hh = Math.floor(totalSeconds / 3600);
  const mm = Math.floor((totalSeconds % 3600) / 60);
  const ss = Math.floor(totalSeconds % 60);
  const ff = Math.floor((totalSeconds - Math.floor(totalSeconds)) * rateHz);
  const pad = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${pad(hh)}:${pad(mm)}:${pad(ss)}:${pad(ff)}`;
}
