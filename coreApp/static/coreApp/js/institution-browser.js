// Let signed-in users browse institutions by typed city or current location.
const citySearchForm = document.querySelector("#city-search-form");
const cityInput = document.querySelector("#browse-city");
const stateInput = document.querySelector("#browse-state");
const useLocationButton = document.querySelector("#browse-use-location");
const locationStatus = document.querySelector("#browse-location-status");

if (citySearchForm && cityInput && stateInput && useLocationButton && locationStatus) {
    useLocationButton.addEventListener("click", () => {
        if (!navigator.geolocation) {
            locationStatus.textContent = "Current location is not supported. Enter your city and state instead.";
            return;
        }

        useLocationButton.disabled = true;
        locationStatus.textContent = "Finding your current city…";

        navigator.geolocation.getCurrentPosition(async ({ coords }) => {
            try {
                const result = await window.findItGeocoding.reverse(
                    coords.latitude,
                    coords.longitude,
                );
                const address = result.address || {};
                const city = address.city
                    || address.town
                    || address.village
                    || address.municipality;
                const state = address.state;

                if (!city || !state) {
                    throw new Error("The current location did not include a city and state.");
                }

                cityInput.value = city;
                stateInput.value = state;
                locationStatus.textContent = `Showing institutions near ${city}, ${state}.`;
                citySearchForm.requestSubmit();
            } catch (error) {
                locationStatus.textContent = "We could not identify your city. Enter it manually instead.";
                useLocationButton.disabled = false;
            }
        }, (error) => {
            const messages = {
                1: "Location permission was denied. Enter your city and state instead.",
                2: "Your location could not be determined. Try again or enter it manually.",
                3: "The location request timed out. Try again or enter it manually.",
            };
            locationStatus.textContent = messages[error.code]
                || "Unable to get your location. Enter your city and state instead.";
            useLocationButton.disabled = false;
        }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 });
    });
}
