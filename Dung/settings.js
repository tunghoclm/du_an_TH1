// =========================
// LẤY ELEMENT
// =========================

const displayName = document.getElementById("display-name");
const email = document.getElementById("email");

const notificationToggle =
    document.getElementById("notification-toggle");

const transactionToggle =
    document.getElementById("transaction-toggle");

const darkModeToggle =
    document.getElementById("dark-mode-toggle");

const saveButton =
    document.getElementById("save-settings");

const changePasswordButton =
    document.getElementById("change-password");

const logoutButton =
    document.getElementById("logout-button");


// =========================
// DỮ LIỆU MẶC ĐỊNH
// =========================

let settings = JSON.parse(
    localStorage.getItem("settings")
) || {

    displayName: "Bùi Chính Minh Dũng",

    email: "dung@example.com",

    notification: true,

    transactionNotification: true,

    darkMode: false
};


// =========================
// HIỂN THỊ CÀI ĐẶT
// =========================

function loadSettings() {

    displayName.value = settings.displayName;

    email.value = settings.email;

    notificationToggle.checked =
        settings.notification;

    transactionToggle.checked =
        settings.transactionNotification;

    darkModeToggle.checked =
        settings.darkMode;

    applyDarkMode();
}


// =========================
// DARK MODE
// =========================

function applyDarkMode() {

    if (settings.darkMode) {

        document.body.classList.add("dark-mode");

    } else {

        document.body.classList.remove("dark-mode");

    }
}


// =========================
// LƯU CÀI ĐẶT
// =========================

saveButton.addEventListener("click", function () {

    settings.displayName =
        displayName.value.trim();

    settings.email =
        email.value.trim();

    settings.notification =
        notificationToggle.checked;

    settings.transactionNotification =
        transactionToggle.checked;

    settings.darkMode =
        darkModeToggle.checked;


    localStorage.setItem(
        "settings",
        JSON.stringify(settings)
    );


    applyDarkMode();

    alert("Đã lưu cài đặt!");
});


// =========================
// ĐỔI MẬT KHẨU
// =========================

changePasswordButton.addEventListener(
    "click",
    function () {

        const oldPassword =
            prompt("Nhập mật khẩu hiện tại:");

        if (oldPassword === null) {
            return;
        }

        const newPassword =
            prompt("Nhập mật khẩu mới:");

        if (newPassword === null) {
            return;
        }

        if (newPassword.length < 6) {

            alert(
                "Mật khẩu mới phải có ít nhất 6 ký tự!"
            );

            return;
        }

        alert(
            "Đổi mật khẩu thành công!"
        );
    }
);


// =========================
// ĐĂNG XUẤT
// =========================

logoutButton.addEventListener(
    "click",
    function () {

        const confirmLogout =
            confirm(
                "Bạn có chắc muốn đăng xuất?"
            );

        if (confirmLogout) {

            window.location.href =
                "login.html";
        }
    }
);


// =========================
// LOAD
// =========================

loadSettings();