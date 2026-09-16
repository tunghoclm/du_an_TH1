
// SMART PARKING - HISTORY.JS


// 1. LẤY PHẦN TỬ HTML

const tableBody =
    document.getElementById(
        "history-table-body"
    );
const emptyHistory =
    document.getElementById(
        "empty-history"
    );
const resultCount =
    document.getElementById(
        "result-count"
    );
const totalHistory =
    document.getElementById(
        "total-history"
    );
const totalIn =
    document.getElementById(
        "total-in"
    );
const totalOut =
    document.getElementById(
        "total-out"
    );
const todayTotal =
    document.getElementById(
        "today-total"
    );
const searchPlate =
    document.getElementById(
        "search-plate"
    );
const typeFilter =
    document.getElementById(
        "type-filter"
    );
const dateFilter =
    document.getElementById(
        "date-filter"
    );
const resetFilter =
    document.getElementById(
        "reset-filter"
    );
const clearHistory =
    document.getElementById(
        "clear-history"
    );

// 2. LẤY DỮ LIỆU CHUNG

function getVehicleData() {
    return JSON.parse(
        localStorage.getItem(
            "vehicleData"
        )
    ) || [];
}

// 3. LƯU DỮ LIỆU

function saveVehicleData(data) {
    localStorage.setItem(
        "vehicleData",
        JSON.stringify(data)
    );
}

// 4. KIỂM TRA NGÀY HÔM NAY

function isToday(timestamp) {
    if (!timestamp) {
        return false;
    }
    const date =
        new Date(timestamp);
    const today =
        new Date();
    return (
        date.getDate() ===
        today.getDate()
        &&
        date.getMonth() ===
        today.getMonth()
        &&
        date.getFullYear() ===
        today.getFullYear()
    );
}

// 5. ĐỊNH DẠNG THỜI GIAN

function formatTime(vehicle) {
    // Nếu có timestamp
    if (vehicle.timestamp) {
        return new Date(
            vehicle.timestamp
        ).toLocaleString(
            "vi-VN"
        );
    }
    // Dữ liệu cũ
    if (vehicle.time) {
        return vehicle.time;
    }
    return "Không rõ";
}

// 6. LỌC DỮ LIỆU

function getFilteredData() {
    const vehicleData =
        getVehicleData();
    const keyword =
        searchPlate.value
            .trim()
            .toUpperCase();
    const selectedType =
        typeFilter.value;
    const selectedDate =
        dateFilter.value;
    return vehicleData.filter(
        vehicle => {
            // ==========================================
            // LỌC BIỂN SỐ
            // ==========================================
            const plate =
                (
                    vehicle.plateNumber ||
                    ""
                ).toUpperCase();
            if (
                keyword !== "" &&
                !plate.includes(keyword)
            ) {
                return false;
            }
            // ==========================================
            // LỌC LOẠI
            // ==========================================
            if (
                selectedType !== "all" &&
                vehicle.type !== selectedType
            ) {
                return false;
            }
            // ==========================================
            // LỌC NGÀY
            // ==========================================
            if (selectedDate) {
                if (!vehicle.timestamp) {
                    return false;
                }
                const date =
                    new Date(
                        vehicle.timestamp
                    );
                const year =
                    date.getFullYear();
                const month =
                    String(
                        date.getMonth() + 1
                    ).padStart(2, "0");
                const day =
                    String(
                        date.getDate()
                    ).padStart(2, "0");
                const vehicleDate =
                    `${year}-${month}-${day}`;
                if (
                    vehicleDate !==
                    selectedDate
                ) {
                    return false;
                }
            }
            return true;
        }
    );
}

// 7. HIỂN THỊ LỊCH SỬ

function renderHistory() {
    const data =
        getFilteredData();
    // Xóa bảng cũ
    tableBody.innerHTML = "";
    // ==========================================
    // SẮP XẾP MỚI NHẤT TRƯỚC
    // ==========================================
    data.sort(
        (a, b) => {
            return (
                (b.timestamp || 0) -
                (a.timestamp || 0)
            );
        }
    );
    // ==========================================
    // KHÔNG CÓ DỮ LIỆU
    // ==========================================
    if (data.length === 0) {
        emptyHistory.style.display =
            "block";
        resultCount.textContent =
            "0 bản ghi";
        return;
    }
    emptyHistory.style.display =
        "none";
    resultCount.textContent =
        `${data.length} bản ghi`;
    // ==========================================
    // TẠO DÒNG
    // ==========================================
    data.forEach(
        (vehicle, index) => {
            const row =
                document.createElement(
                    "tr"
                );
            // ======================================
            // STT
            // ======================================
            const numberCell =
                document.createElement(
                    "td"
                );
            numberCell.textContent =
                index + 1;
            // ======================================
            // BIỂN SỐ
            // ======================================
            const plateCell =
                document.createElement(
                    "td"
                );
            plateCell.className =
                "plate-number";
            plateCell.textContent =
                vehicle.plateNumber ||
                "Không rõ";
            // ======================================
            // VỊ TRÍ
            // ======================================
            const slotCell =
                document.createElement(
                    "td"
                );
            slotCell.textContent =
                vehicle.slotName ||
                "Không rõ";
            // ======================================
            // LOẠI GIAO DỊCH
            // ======================================
            const typeCell =
                document.createElement(
                    "td"
                );
            const badge =
                document.createElement(
                    "span"
                );
            badge.className =
                "badge";
            if (
                vehicle.type === "in"
            ) {
                badge.classList.add(
                    "badge-in"
                );
                badge.textContent =
                    "Xe vào";
            }
            else {
                badge.classList.add(
                    "badge-out"
                );
                badge.textContent =
                    "Xe ra";
            }
            typeCell.appendChild(
                badge
            );
            // ======================================
            // THỜI GIAN
            // ======================================
            const timeCell =
                document.createElement(
                    "td"
                );
            timeCell.textContent =
                formatTime(vehicle);
            // ======================================
            // GHÉP DÒNG
            // ======================================
            row.appendChild(
                numberCell
            );
            row.appendChild(
                plateCell
            );
            row.appendChild(
                slotCell
            );
            row.appendChild(
                typeCell
            );
            row.appendChild(
                timeCell
            );
            tableBody.appendChild(
                row
            );
        }
    );
}

// 8. CẬP NHẬT THỐNG KÊ

function updateHistoryStatistics() {
    const data =
        getVehicleData();
    const inCount =
        data.filter(
            vehicle =>
                vehicle.type === "in"
        ).length;
    const outCount =
        data.filter(
            vehicle =>
                vehicle.type === "out"
        ).length;
    const todayCount =
        data.filter(
            vehicle =>
                isToday(
                    vehicle.timestamp
                )
        ).length;
    totalHistory.textContent =
        data.length;
    totalIn.textContent =
        inCount;
    totalOut.textContent =
        outCount;
    todayTotal.textContent =
        todayCount;
}

// 9. TÌM KIẾM

searchPlate.addEventListener(
    "input",
    function () {
        renderHistory();
    }
);

// 10. LỌC LOẠI

typeFilter.addEventListener(
    "change",
    function () {
        renderHistory();
    }
);

// 11. LỌC NGÀY

dateFilter.addEventListener(
    "change",
    function () {
        renderHistory();
    }
);

// 12. ĐẶT LẠI BỘ LỌC

resetFilter.addEventListener(
    "click",
    function () {
        searchPlate.value =
            "";
        typeFilter.value =
            "all";
        dateFilter.value =
            "";
        renderHistory();
    }
);

// 13. XÓA TOÀN BỘ LỊCH SỬ

clearHistory.addEventListener(
    "click",
    function () {
        const data =
            getVehicleData();
        if (data.length === 0) {
            alert(
                "Hiện chưa có lịch sử để xóa."
            );
            return;
        }
        const confirmDelete =
            confirm(
                "Bạn có chắc muốn xóa toàn bộ lịch sử xe ra vào không?"
            );
        if (!confirmDelete) {
            return;
        }
        saveVehicleData([]);
        renderHistory();
        updateHistoryStatistics();
        alert(
            "Đã xóa toàn bộ lịch sử."
        );
    }
);

// 14. TỰ ĐỘNG CẬP NHẬT

// Khi chuyển từ parking / vehical
// sang history thì đọc dữ liệu mới nhất.
window.addEventListener(
    "storage",
    function () {
        renderHistory();
        updateHistoryStatistics();
    }
);

// 15. KHỞI TẠO

renderHistory();
updateHistoryStatistics();