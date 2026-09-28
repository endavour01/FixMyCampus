const reportForm = document.getElementById("report-form");
const photoInput = document.getElementById("photo");
const photoPreview = document.getElementById("photo-preview");
const previewImage = document.getElementById("preview-image");
const previewFilename = document.getElementById("preview-filename");
const selectedFile = document.getElementById("selected-file");
const summary = document.getElementById("form-error-summary");
const removePhotoButton = document.getElementById("remove-photo");
const maxPhotoSize = 5 * 1024 * 1024;
const allowedPhotoTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
let previewUrl = null;

function setFieldError(fieldName, message) {
    const field = reportForm.elements[fieldName];
    const error = document.getElementById(`${field.id}-error`);
    field.setAttribute("aria-invalid", "true");
    error.textContent = message;
}

function clearFieldError(fieldName) {
    const field = reportForm.elements[fieldName];
    const error = document.getElementById(`${field.id}-error`);
    field.removeAttribute("aria-invalid");
    error.textContent = "";
}

function clearAllErrors() {
    ["title", "description", "category", "location_id", "photo"].forEach(clearFieldError);
    summary.hidden = true;
    summary.textContent = "";
}

function showPhotoError(message) {
    photoInput.setAttribute("aria-invalid", "true");
    document.getElementById("photo-error").textContent = message;
}

function clearPhotoError() {
    photoInput.removeAttribute("aria-invalid");
    document.getElementById("photo-error").textContent = "";
}

function releasePreview() {
    if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
        previewUrl = null;
    }
}

function clearPreview() {
    releasePreview();
    photoPreview.hidden = true;
    previewImage.removeAttribute("src");
    previewFilename.textContent = "";
    selectedFile.textContent = "No file selected";
}

if (reportForm) {
    reportForm.addEventListener("submit", (event) => {
        clearAllErrors();
        const invalidFields = [];
        const requiredFields = [
            ["title", "Enter a short title for the issue."],
            ["description", "Describe what needs attention."],
            ["category", "Choose a category from the list."],
            ["location_id", "Choose a campus location."],
        ];

        requiredFields.forEach(([fieldName, message]) => {
            const field = reportForm.elements[fieldName];
            const value = field.value.trim();
            if (!value) {
                setFieldError(fieldName, message);
                invalidFields.push(field);
            }
        });

        if (reportForm.elements.title.value.trim().length > 120) {
            setFieldError("title", "Keep the title to 120 characters or fewer.");
            invalidFields.push(reportForm.elements.title);
        }

        if (reportForm.elements.description.value.trim().length > 2000) {
            setFieldError("description", "Keep the description to 2,000 characters or fewer.");
            invalidFields.push(reportForm.elements.description);
        }

        const photo = photoInput.files[0];
        if (photo) {
            const extensionIsAllowed = /\.(jpe?g|png|webp)$/i.test(photo.name);
            const typeIsAllowed = !photo.type || allowedPhotoTypes.has(photo.type);
            if (!extensionIsAllowed || !typeIsAllowed) {
                showPhotoError("Choose a JPEG, PNG, or WebP image.");
                invalidFields.push(photoInput);
            } else if (photo.size > maxPhotoSize) {
                showPhotoError("The image must be 5 MB or smaller.");
                invalidFields.push(photoInput);
            }
        }

        if (invalidFields.length > 0) {
            event.preventDefault();
            summary.textContent = "Please review the highlighted fields before submitting your report.";
            summary.hidden = false;
            invalidFields[0].focus();
        }
    });

    ["title", "description", "category", "location_id"].forEach((fieldName) => {
        const field = reportForm.elements[fieldName];
        field.addEventListener("input", () => clearFieldError(fieldName));
        field.addEventListener("change", () => clearFieldError(fieldName));
    });
}

if (photoInput) {
    photoInput.addEventListener("change", () => {
        clearPhotoError();
        const photo = photoInput.files[0];
        if (!photo) {
            clearPreview();
            return;
        }

        const extensionIsAllowed = /\.(jpe?g|png|webp)$/i.test(photo.name);
        const typeIsAllowed = !photo.type || allowedPhotoTypes.has(photo.type);
        if (!extensionIsAllowed || !typeIsAllowed) {
            clearPreview();
            showPhotoError("Choose a JPEG, PNG, or WebP image.");
            return;
        }
        if (photo.size > maxPhotoSize) {
            clearPreview();
            showPhotoError("The image must be 5 MB or smaller.");
            return;
        }

        releasePreview();
        previewUrl = URL.createObjectURL(photo);
        previewImage.src = previewUrl;
        previewFilename.textContent = photo.name;
        selectedFile.textContent = photo.name;
        photoPreview.hidden = false;
    });
}

if (removePhotoButton) {
    removePhotoButton.addEventListener("click", () => {
        photoInput.value = "";
        clearPhotoError();
        clearPreview();
        photoInput.focus();
    });
}