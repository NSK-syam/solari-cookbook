import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApproximatePropertyMap } from "./ApproximatePropertyMap";

describe("ApproximatePropertyMap", () => {
  it("shows a real-map disclosure without implying an exact property location", () => {
    render(<ApproximatePropertyMap />);

    expect(screen.getByRole("region", { name: /interactive real map/i })).toHaveAttribute(
      "data-map-status",
      "unavailable",
    );
    expect(screen.getByText("REAL OPENSTREETMAP BASEMAP")).toBeInTheDocument();
    expect(screen.getByText("MILTON, DELAWARE")).toBeInTheDocument();
    expect(screen.getByText(/synthetic demonstration.*exact parcel not displayed/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /OpenStreetMap contributors/i })).toHaveAttribute(
      "href",
      "https://www.openstreetmap.org/copyright",
    );
    expect(screen.queryByText(/91 Marsh Road/i)).not.toBeInTheDocument();
  });
});
