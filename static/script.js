function uploadImage() {
    let imageInput = document.getElementById("imageInput").files[0];
    let language = document.getElementById("languageSelect").value;
    let formData = new FormData();
    formData.append("image", imageInput);
    formData.append("language", language); // Send selected language

    fetch("/upload", {
        method: "POST",
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        let resultContainer = document.getElementById("result-container");
        let resultBox = document.getElementById("result");

        resultBox.innerHTML = `<strong>${data.disease_info}</strong>`;
        resultContainer.classList.remove("hidden");
    })
    .catch(error => console.error("Error:", error));
}

function captureImage() {
    const video = document.getElementById('video'); // Use the existing video element
    const canvas = document.getElementById('canvas'); // Use the existing canvas element
    const context = canvas.getContext('2d');
    const language = document.getElementById('languageSelect').value;
    const resultContainer = document.getElementById('result-container');
    const resultBox = document.getElementById('result');

    // Ensure the video stream is ready before capturing
    if (video.readyState !== 4) { // 4 = HAVE_ENOUGH_DATA
        alert("Video stream is not ready. Please wait a moment and try again.");
        return;
    }

    // Set canvas size to match video
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    // Draw video frame on canvas
    context.drawImage(video, 0, 0, canvas.width, canvas.height);

    // Stop camera stream
    video.srcObject.getTracks().forEach(track => track.stop());
    video.style.display = 'none';
    document.getElementById('captureBtn').classList.add('hidden');

    // Convert image to Blob
    canvas.toBlob((blob) => {
        let formData = new FormData();
        formData.append("image", blob, "captured_image.png");
        formData.append("language", language);

        // Send image to server
        fetch("/upload", {
            method: "POST",
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            resultBox.innerHTML = `<strong>${data.disease_info}</strong>`;
            resultContainer.classList.remove("hidden");
        })
        .catch(error => console.error("Error uploading image:", error));
    }, "image/png");
}
document.addEventListener("DOMContentLoaded", function () {
    const stars = document.querySelectorAll(".star");
    const submitBtn = document.getElementById("submitFeedback");

    let selectedRating = 0;

    // Star click event
    stars.forEach(star => {
        star.addEventListener("click", function () {
            selectedRating = this.getAttribute("data-value");
            stars.forEach(s => s.style.color = "#ccc"); // Reset color
            this.style.color = "gold"; // Highlight selected star and previous stars
            let prev = this.previousElementSibling;
            while (prev) {
                prev.style.color = "gold";
                prev = prev.previousElementSibling;
            }
        });
    });

    // Submit Feedback
    submitBtn.addEventListener("click", function () {
        const comment = document.getElementById("commentBox").value;

        if (selectedRating == 0) {
            alert("Please select a rating before submitting.");
            return;
        }

        fetch("/submit_feedback", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ rating: selectedRating, comment: comment })
        })
        .then(response => response.json())
        .then(data => {
            alert(data.message);
            document.getElementById("commentBox").value = "";
            stars.forEach(s => s.style.color = "#ccc"); // Reset stars
        })
        .catch(error => console.error("Error:", error));
    });
});

