import { create } from "zustand";

/** A request to bring one listing into view in the properties panel. */
export interface PropertyFocusRequest {
  propertyId: number;
  /** Changes on every request, so asking for the same listing twice still scrolls to it. */
  nonce: number;
}

interface PropertyFocusState {
  request: PropertyFocusRequest | null;
  focusProperty: (propertyId: number) => void;
}

let nextNonce = 0;

export const usePropertyFocusStore = create<PropertyFocusState>((set) => ({
  request: null,
  focusProperty: (propertyId) => set({ request: { propertyId, nonce: ++nextNonce } }),
}));
