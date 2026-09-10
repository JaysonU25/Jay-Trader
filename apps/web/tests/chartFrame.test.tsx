import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ChartFrame } from "@/components/ChartFrame";
import { DataTable } from "@/components/DataTable";

describe("ChartFrame", () => {
  it("shows the chart first and swaps to the table on demand", async () => {
    render(
      <ChartFrame
        title="10-Year Treasury"
        chart={<div data-testid="chart-slot" />}
        table={
          <DataTable
            caption="10-Year Treasury"
            columns={[
              { key: "d", header: "Date" },
              { key: "v", header: "Value", align: "right" },
            ]}
            rows={[{ d: "2026-09-01", v: 4.3 }]}
          />
        }
      />,
    );

    expect(screen.getByTestId("chart-slot")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Table" }));

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "4.3" })).toBeInTheDocument();
    expect(screen.queryByTestId("chart-slot")).not.toBeInTheDocument();
  });

  it("marks the active view with aria-pressed", async () => {
    render(<ChartFrame title="t" chart={<div />} table={<div />} />);
    expect(screen.getByRole("button", { name: "Chart" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Table" }));
    expect(screen.getByRole("button", { name: "Table" })).toHaveAttribute("aria-pressed", "true");
  });
});
