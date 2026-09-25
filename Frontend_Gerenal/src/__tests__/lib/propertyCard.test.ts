import { describe, expect, it } from "vitest";
import {
  cleanPropQaPipeTitle,
  pickCardTitle,
  pickFigmaCardTitle,
  pickAgencyLogoUrl,
  pickAgentImageUrl,
  pickCardListingHref,
} from "@/lib/propertyCard";
import type { PropertyCard } from "@/store/chatStore";

describe("cleanPropQaPipeTitle", () => {
  it("strips beds/type/purpose pipe segments", () => {
    expect(
      cleanPropQaPipeTitle(
        "2 B/R | Apartment | Mercedes Benz Places By Binghatti, Downtown Dubai, Dubai | for Sale",
      ),
    ).toBe("Mercedes Benz Places By Binghatti, Downtown Dubai, Dubai");
  });

  it("returns plain titles unchanged (deduped)", () => {
    expect(cleanPropQaPipeTitle("Marina Gate, Dubai Marina")).toBe(
      "Marina Gate, Dubai Marina",
    );
  });
});

describe("pickFigmaCardTitle", () => {
  it("uses cleaned pipe title when richer than location", () => {
    const card: PropertyCard = {
      title_en:
        "2 B/R | Apartment | Mercedes Benz Places By Binghatti, Downtown Dubai, Dubai | for Sale",
      building_name: "Mercedes Benz Places by Binghatti",
      project_name: "Mercedes Benz Places by Binghatti",
      rooms: 2,
      type: "Apartment",
    };
    expect(pickFigmaCardTitle(card)).toBe(
      "Mercedes Benz Places By Binghatti, Downtown Dubai, Dubai",
    );
  });

  it("falls back to beds + type when cleaned title matches location", () => {
    const card: PropertyCard = {
      title: "Marina Gate",
      building_name: "Marina Gate",
      rooms: 2,
      type: "Apartment",
    };
    expect(pickFigmaCardTitle(card)).toBe("2 Bedroom Apartment");
  });
});

describe("pickCardTitle", () => {
  it("no longer dumps full pipe metadata as the title", () => {
    expect(
      pickCardTitle({
        title_en: "3 B/R | Villa | Arabian Ranches | for Rent",
      }),
    ).toBe("Arabian Ranches");
  });
});

describe("logo / avatar pickers", () => {
  it("reads agency_logo_url and agent_image_url", () => {
    const card: PropertyCard = {
      agency_logo_url: "https://cdn/logo.png",
      agent_image_url: "https://cdn/agent.jpg",
    };
    expect(pickAgencyLogoUrl(card)).toBe("https://cdn/logo.png");
    expect(pickAgentImageUrl(card)).toBe("https://cdn/agent.jpg");
  });
});

describe("pickCardListingHref", () => {
  it("builds a propqa.ai /property/ URL from a slug", () => {
    expect(pickCardListingHref({ slug: "south-bay-1-villa" })).toBe(
      "https://propqa.ai/property/south-bay-1-villa",
    );
  });

  it("appends the listing id when the slug does not already end with it", () => {
    expect(pickCardListingHref({ slug: "south-bay-1-villa", id: 17258 })).toBe(
      "https://propqa.ai/property/south-bay-1-villa-17258",
    );
  });

  it("does not double-append an id already on the slug", () => {
    expect(
      pickCardListingHref({
        slug: "south-bay-1-villa-17258",
        id: 17258,
      }),
    ).toBe("https://propqa.ai/property/south-bay-1-villa-17258");
  });

  it("rewrites a localhost listing URL to propqa.ai", () => {
    expect(
      pickCardListingHref({ url: "http://localhost:5173/properties/south-bay" }),
    ).toBe("https://propqa.ai/property/south-bay");
  });
});
