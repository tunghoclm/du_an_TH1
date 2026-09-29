// =========================
// DỮ LIỆU NGƯỜI DÙNG
// =========================

let userData = JSON.parse(localStorage.getItem("userData")) || {

    username: "dung123",
    fullname: "Nguyễn Văn Dũng",
    phone: "09xxxxxxxx",
    email: "dung@example.com",
    birthday: "01/01/2000",
    joinDate: "15/09/2026",

    balance: 250000,

    transactions: [
        {
            date: "19/09/2026 18:30",
            method: "Chuyển khoản",
            amount: 100000,
            status: "Thành công"
        },
        {
            date: "18/09/2026 14:20",
            method: "Ví điện tử",
            amount: 200000,
            status: "Thành công"
        },
        {
            date: "15/09/2026 09:10",
            method: "Chuyển khoản",
            amount: 100000,
            status: "Thành công"
        }
    ]
};


// =========================
// LƯU DỮ LIỆU
// =========================

function saveData() {
    localStorage.setItem(
        "userData",
        JSON.stringify(userData)
    );
}


// =========================
// ĐỊNH DẠNG TIỀN
// =========================

function formatMoney(number) {
    return number.toLocaleString("vi-VN") + "đ";
}


// =========================
// HIỂN THỊ THÔNG TIN
// =========================

function displayUserData() {

    document.getElementById("username").textContent =
        userData.username;

    document.getElementById("fullname").textContent =
        userData.fullname;

    document.getElementById("phone").textContent =
        userData.phone;

    document.getElementById("email").textContent =
        userData.email;

    document.getElementById("birthday").textContent =
        userData.birthday;

    document.getElementById("join-date").textContent =
        userData.joinDate;

    document.getElementById("balance").textContent =
        formatMoney(userData.balance);
}


// =========================
// HIỂN THỊ LỊCH SỬ
// =========================

function displayTransactions() {

    const transactionList =
        document.getElementById("transaction-list");

    transactionList.innerHTML = `
        <div class="transaction-row transaction-header">
            <span>Thời gian</span>
            <span>Phương thức</span>
            <span>Số tiền</span>
            <span>Trạng thái</span>
        </div>
    `;

    userData.transactions.forEach(function(transaction) {

        const row = document.createElement("div");

        row.className = "transaction-row";

        row.innerHTML = `
            <span>${transaction.date}</span>

            <span>${transaction.method}</span>

            <strong>
                +${formatMoney(transaction.amount)}
            </strong>

            <span class="status success">
                ${transaction.status}
            </span>
        `;

        transactionList.appendChild(row);
    });
}


// =========================
// CHỈNH SỬA THÔNG TIN
// =========================

document
    .getElementById("edit-button")
    .addEventListener("click", function() {

        const fullname = prompt(
            "Nhập họ và tên:",
            userData.fullname
        );

        if (fullname === null) {
            return;
        }

        const phone = prompt(
            "Nhập số điện thoại:",
            userData.phone
        );

        if (phone === null) {
            return;
        }

        const email = prompt(
            "Nhập email:",
            userData.email
        );

        if (email === null) {
            return;
        }

        const birthday = prompt(
            "Nhập ngày sinh:",
            userData.birthday
        );

        if (birthday === null) {
            return;
        }


        // Cập nhật dữ liệu

        userData.fullname = fullname;
        userData.phone = phone;
        userData.email = email;
        userData.birthday = birthday;


        // Lưu

        saveData();


        // Hiển thị lại

        displayUserData();


        alert("Đã cập nhật thông tin!");
    });


// =========================
// NẠP TIỀN
// =========================

document
    .querySelector(".confirm-button")
    .addEventListener("click", function() {

        const amountSelect =
            document.getElementById("amount");

        const amount =
            Number(amountSelect.value);


        // Lấy phương thức thanh toán

        const payment =
            document.querySelector(
                'input[name="payment"]:checked'
            );


        let method = "Chuyển khoản";


        if (payment) {

            const label =
                payment.parentElement.textContent.trim();

            if (label.includes("Ví điện tử")) {
                method = "Ví điện tử";
            }

            if (label.includes("QR Code")) {
                method = "QR Code";
            }
        }


        // Cộng tiền

        userData.balance += amount;


        // Lấy thời gian hiện tại

        const now = new Date();

        const date =
            now.toLocaleDateString("vi-VN") +
            " " +
            now.toLocaleTimeString("vi-VN", {
                hour: "2-digit",
                minute: "2-digit"
            });


        // Thêm giao dịch

        userData.transactions.unshift({

            date: date,

            method: method,

            amount: amount,

            status: "Thành công"
        });


        // Lưu dữ liệu

        saveData();


        // Cập nhật giao diện

        displayUserData();

        displayTransactions();


        alert(
            "Nạp " +
            formatMoney(amount) +
            " thành công!"
        );
    });


// =========================
// KHỞI ĐỘNG
// =========================

displayUserData();

displayTransactions();