// A string or number from the data with no provenance tooltip (for running text and labels).
import { show, type FigProps } from "./Fig";

export function Traced({ src, as: Tag = "span", ...fmt }: Pick<FigProps, "src" | "digits" | "scale" | "sci" | "group" | "sign"> & { as?: "span" | "p" | "div" | "strong" }) {
  return (
    <Tag data-src={src} data-scale={fmt.scale && fmt.scale !== 1 ? fmt.scale : undefined}>
      {show(src, fmt)}
    </Tag>
  );
}
