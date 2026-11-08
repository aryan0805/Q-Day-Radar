import type { Metadata } from "next";
import { LabView } from "../../components/lab/LabView";

export const metadata: Metadata = { title: "Lab" };

export default function Page() {
  return <LabView />;
}
