const issueUpdateForm = document.getElementById("issue-update-form");

if (issueUpdateForm) {
    const statusField = document.getElementById("issue-status");
    const assignmentField = document.getElementById("issue-assignee");
    const priorityField = document.getElementById("issue-priority");
    const commentField = document.getElementById("status-comment");
    const feedback = document.getElementById("status-update-feedback");
    const submitButton = issueUpdateForm.querySelector("button[type='submit']");
    const csrfToken = issueUpdateForm.querySelector("[name='csrf_token']").value;
    const statusWasResolved = issueUpdateForm.dataset.currentStatus === "resolved";

    issueUpdateForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        feedback.classList.remove("is-error");
        feedback.textContent = "";

        if (statusField.value === "resolved" && !statusWasResolved && !commentField.value.trim()) {
            feedback.classList.add("is-error");
            feedback.textContent = "Add a comment before marking this issue resolved.";
            commentField.focus();
            return;
        }

        const payload = {
            status: statusField.value,
            assigned_to: assignmentField.value ? Number(assignmentField.value) : null,
            priority: priorityField.value,
            comment: commentField.value.trim(),
        };

        submitButton.disabled = true;
        submitButton.textContent = "Saving…";
        try {
            const response = await fetch(issueUpdateForm.dataset.patchUrl, {
                method: "PATCH",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken,
                },
                credentials: "same-origin",
                body: JSON.stringify(payload),
            });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.error?.message || "Could not save this report.");
            }

            feedback.textContent = "Changes saved. Refreshing report history…";
            window.location.reload();
        } catch (error) {
            feedback.classList.add("is-error");
            feedback.textContent = error.message || "Could not save this report. Try again.";
            submitButton.disabled = false;
            submitButton.textContent = "Save changes";
        }
    });
}