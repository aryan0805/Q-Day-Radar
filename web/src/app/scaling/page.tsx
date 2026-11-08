import type { Metadata } from "next";
import { ScalingView } from "../../components/scaling/ScalingView";

export const metadata: Metadata = { title: "Scaling" };

export default function Page() {
  return <ScalingView />;
}
