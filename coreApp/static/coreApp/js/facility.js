// Store coordinates for every new facility so searches can rank its distance.
const facilityForm = document.querySelector("#facility-form");
const institutionLocation = document.querySelector("#id_institution_location");
const institutionState = document.querySelector("#id_institution_state");
const facilityLatitude = document.querySelector("#id_latitude");
const facilityLongitude = document.querySelector("#id_longitude");
const facilityLocationStatus = document.querySelector("#facility-location-status");

if (
    facilityForm && institutionLocation && institutionState
    && facilityLatitude && facilityLongitude && facilityLocationStatus
) {
    const clearCoordinates = () => {
        facilityLatitude.value = "";
        facilityLongitude.value = "";
    };

    institutionLocation.addEventListener("input", clearCoordinates);
    institutionState.addEventListener("input", clearCoordinates);

    facilityForm.addEventListener("submit", async (event) => {
        if (facilityLatitude.value && facilityLongitude.value) {
            return;
        }

        event.preventDefault();
        facilityLocationStatus.textContent = "Finding the institution coordinates…";

        try {
            const point = await window.findItGeocoding.forward(
                institutionLocation.value.trim(),
                institutionState.value.trim(),
            );
            facilityLatitude.value = Number(point.latitude).toFixed(7);
            facilityLongitude.value = Number(point.longitude).toFixed(7);
            facilityForm.requestSubmit();
        } catch (error) {
            facilityLocationStatus.textContent = "We could not find this institution address. Check the locality and state, then try again.";
        }
    });
}
