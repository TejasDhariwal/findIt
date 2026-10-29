// Use OpenStreetMap Nominatim for text-to-coordinate and coordinate-to-text lookups.
window.findItGeocoding = {
    async forward(location, state) {
        const parameters = new URLSearchParams({
            format: "jsonv2",
            addressdetails: "1",
            limit: "1",
            q: `${location}, ${state}`,
        });
        const response = await fetch(
            `https://nominatim.openstreetmap.org/search?${parameters}`,
            { headers: { "Accept-Language": navigator.language } },
        );
        if (!response.ok) {
            throw new Error("Address lookup request failed.");
        }

        const [result] = await response.json();
        if (!result) {
            throw new Error("No matching address was found.");
        }
        return { latitude: result.lat, longitude: result.lon };
    },

    async reverse(latitude, longitude) {
        const parameters = new URLSearchParams({
            format: "jsonv2",
            lat: latitude,
            lon: longitude,
            zoom: "18",
            addressdetails: "1",
        });
        const response = await fetch(
            `https://nominatim.openstreetmap.org/reverse?${parameters}`,
            { headers: { "Accept-Language": navigator.language } },
        );
        if (!response.ok) {
            throw new Error("Address lookup request failed.");
        }
        return response.json();
    },
};
