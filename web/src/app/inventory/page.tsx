import type { Metadata } from "next";
import { InventoryView } from "../../components/inventory/InventoryView";

export const metadata: Metadata = { title: "Inventory" };

export default function Page() {
  return <InventoryView />;
}
