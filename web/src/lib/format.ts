const SUP: Record<string, string> = {
  "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹", "-": "⁻",
};

/** 6.35 × 10⁶ (the gate reads the mantissa and the exponent, and tolerates half the last digit). */
export function sci(v: number, digits: number): string {
  if (v === 0) return (0).toFixed(digits);
  const exp = Math.floor(Math.log10(Math.abs(v)));
  const mant = v / 10 ** exp;
  let m = mant.toFixed(digits);
  let e = exp;
  if (Math.abs(Number(m)) >= 10) {
    m = (mant / 10).toFixed(digits);
    e += 1;
  }
  return `${m} × 10${[...String(e)].map((c) => SUP[c] ?? c).join("")}`;
}

export interface NumFmt {
  digits?: number;
  scale?: number;
  sci?: boolean;
  group?: boolean;
  sign?: boolean;
}

export function fmtNumber(v: number, f: NumFmt = {}): string {
  const d = f.digits ?? 0;
  const x = v * (f.scale ?? 1);
  if (f.sci) return sci(x, d);
  let s = x.toFixed(d);
  if (f.group) s = Number(s).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  if (f.sign && x > 0) s = `+${s}`;
  return s.replace("-", "−");
}
