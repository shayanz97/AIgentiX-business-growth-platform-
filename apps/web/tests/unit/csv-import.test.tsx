import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CsvImport } from "@/components/research/csv-import";

const post = vi.fn();
const get = vi.fn();
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: { POST: (...a: unknown[]) => post(...a), GET: (...a: unknown[]) => get(...a) },
}));

const row = (line: number, name: string, status: string, errors: string[] = []) => ({
  line,
  name,
  website_url: status === "invalid" ? null : `https://${name.toLowerCase()}.example`,
  canonical_domain: status === "invalid" ? null : `${name.toLowerCase()}.example`,
  status,
  errors,
  company_id: null,
});

const preview = {
  dry_run: true,
  total_rows: 3,
  new: 1,
  existing: 1,
  duplicates: 0,
  invalid: 1,
  created: 0,
  linked_to_project: 0,
  rows: [row(2, "Acme", "new"), row(3, "Globex", "existing"), row(4, "Bad", "invalid", ["Website is not a valid URL"])],
};

describe("CsvImport", () => {
  beforeEach(() => {
    post.mockReset();
    get.mockReset();
    get.mockResolvedValue({ data: { items: [], total: 0, limit: 100, offset: 0 } });
  });

  it("previews and then imports", async () => {
    post.mockResolvedValueOnce({ data: preview });
    post.mockResolvedValueOnce({ data: { ...preview, dry_run: false, created: 1, linked_to_project: 0 } });
    render(<CsvImport />);

    const csv = "name,website\nAcme,acme.example\n";
    await userEvent.upload(screen.getByLabelText("CSV file"), new File([csv], "companies.csv", { type: "text/csv" }));
    await userEvent.click(await screen.findByRole("button", { name: "Preview import" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/companies/import", { body: { csv_text: csv, dry_run: true, project_id: null } }),
    );
    expect(await screen.findByText("Website is not a valid URL")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Import preview rows" });
    expect(within(table).getByText("Already exists")).toBeInTheDocument();
    expect(within(table).getByText("Invalid")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Import companies" }));
    await waitFor(() =>
      expect(post).toHaveBeenLastCalledWith("/api/v1/companies/import", { body: { csv_text: csv, dry_run: false, project_id: null } }),
    );
    expect(await screen.findByText("Import complete")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View companies" })).toHaveAttribute("href", "/companies");
  });

  it("rejects files larger than 512 KB without calling the API", async () => {
    render(<CsvImport />);
    const big = new File(["x".repeat(512 * 1024 + 1)], "big.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("CSV file"), big);
    expect(await screen.findByRole("alert")).toHaveTextContent("larger than 512 KB");
    expect(screen.getByRole("button", { name: "Preview import" })).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
  });

  it("shows API errors from the preview", async () => {
    post.mockResolvedValue({ error: { error: { message: "CSV has too many rows" } } });
    render(<CsvImport />);
    await userEvent.upload(screen.getByLabelText("CSV file"), new File(["name\nA"], "a.csv", { type: "text/csv" }));
    await userEvent.click(await screen.findByRole("button", { name: "Preview import" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("CSV has too many rows");
  });
});
