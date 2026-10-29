// Resolve a typed address before submitting so results can be sorted by distance.
const searchForm = document.querySelector("#find-form");
const locationButton = document.querySelector("#use-location");
const locationInput = document.querySelector("#id_location");
const stateInput = document.querySelector("#id_state");
const latitudeInput = document.querySelector("#id_latitude");
const longitudeInput = document.querySelector("#id_longitude");
const locationStatus = document.querySelector("#location-status");

if (searchForm && locationInput && stateInput && latitudeInput && longitudeInput && locationStatus) {
    const clearCoordinates = () => {
        latitudeInput.value = "";
        longitudeInput.value = "";
    };

    // Edited address text must not retain coordinates from an earlier location.
    locationInput.addEventListener("input", clearCoordinates);
    stateInput.addEventListener("input", clearCoordinates);

    searchForm.addEventListener("submit", async (event) => {
        if (latitudeInput.value && longitudeInput.value) {
            return;
        }

        event.preventDefault();
        locationStatus.textContent = "Finding the coordinates for this address…";

        try {
            const point = await window.findItGeocoding.forward(
                locationInput.value.trim(),
                stateInput.value.trim(),
            );
            latitudeInput.value = Number(point.latitude).toFixed(7);
            longitudeInput.value = Number(point.longitude).toFixed(7);
            searchForm.requestSubmit();
        } catch (error) {
            locationStatus.textContent = "We could not find this address. Check the locality and state, or use your current location.";
        }
    });
}

if (locationButton && locationInput && stateInput && latitudeInput && longitudeInput && locationStatus) {
    locationButton.addEventListener("click", () => {
        if (!navigator.geolocation) {
            locationStatus.textContent = "Current location is not supported by this browser. Enter your address instead.";
            return;
        }

        locationButton.disabled = true;
        locationStatus.textContent = "Requesting your location…";

        navigator.geolocation.getCurrentPosition(async ({ coords }) => {
            latitudeInput.value = coords.latitude.toFixed(7);
            longitudeInput.value = coords.longitude.toFixed(7);

            try {
                const result = await window.findItGeocoding.reverse(
                    coords.latitude,
                    coords.longitude,
                );
                const address = result.address || {};
                const locationParts = [
                    address.neighbourhood,
                    address.suburb,
                    address.city_district,
                    address.quarter,
                    address.town,
                    address.city,
                    address.village,
                    address.municipality,
                ].filter(Boolean);
                const uniqueParts = [...new Map(
                    locationParts.map((part) => [part.toLocaleLowerCase(), part]),
                ).values()];

                if (uniqueParts.length > 0) {
                    locationInput.value = uniqueParts.join(", ").slice(0, 255);
                }
                if (address.state) {
                    stateInput.value = address.state.slice(0, 100);
                }
                locationStatus.textContent = address.state && uniqueParts.length
                    ? "Readable location added. Review it before searching."
                    : "Coordinates added, but the address could not be completed. Enter the locality and state.";
            } catch (error) {
                locationStatus.textContent = "Coordinates added, but address lookup failed. Enter the locality and state.";
            } finally {
                locationButton.disabled = false;
            }
        }, (error) => {
            const messages = {
                1: "Location permission was denied. Enter your address manually instead.",
                2: "Your location could not be determined. Try again or enter it manually.",
                3: "The location request timed out. Try again or enter it manually.",
            };
            locationStatus.textContent = messages[error.code] || "Unable to get your location. Enter it manually instead.";
            locationButton.disabled = false;
        }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 });
    });
}
