
// SMART PARKING - VEHICAL.JS


// 1. LẤY DỮ LIỆU TỪ LOCAL STORAGE

function getVehicleData() {
    return JSON.parse(
        localStorage.getItem("vehicleData")
    ) || [];
}

// 2. LẤY CÁC PHẦN TỬ HTML

const vehicleInElement =
    document.getElementById("vehicle-in");
const vehicleOutElement =
    document.getElementById("vehicle-out");
const vehicleInsideElement =
    document.getElementById("vehicle-inside");
const tableBody =
    document.getElementById("vehicle-table-body");
const recordCount =
    document.getElementById("record-count");
const emptyMessage =
    document.getElementById("empty-message");
const vehicleFilter =
    document.getElementById("vehicle-filter");
const plateSearch =
    document.getElementById("plate-search");

// 3. CẬP NHẬT THỐNG KÊ

function updateStatistics() {
    const data =
        getVehicleData();
    // Tổng lượt xe vào
    const totalIn =
        data.filter(
            vehicle =>
                vehicle.type === "in"
        ).length;
    // Tổng lượt xe ra
    const totalOut =
        data.filter(
            vehicle =>
                vehicle.type === "out"
        ).length;
    // Số xe đang trong bãi
    const inside =
        totalIn - totalOut;
    vehicleInElement.textContent =
        totalIn;
    vehicleOutElement.textContent =
        totalOut;
    vehicleInsideElement.textContent =
        Math.max(inside, 0);
}

// 4. HIỂN THỊ BẢNG

function renderTable() {
    const data =
        getVehicleData();
    const filterValue =
        vehicleFilter.value;
    const searchValue =
        plateSearch.value
            .trim()
            .toUpperCase();
    // ==================================================
    // LỌC DỮ LIỆU
    // ==================================================
    const filteredData =
        data.filter(vehicle => {
            // Lọc theo loại
            const matchType =
                filterValue === "all" ||
                vehicle.type === filterValue;
            // Lọc theo biển số
            const matchPlate =
                vehicle.plateNumber
                    .toUpperCase()
                    .includes(searchValue);
            return (
                matchType &&
                matchPlate
            );
        });
    // Xóa bảng cũ
    tableBody.innerHTML = "";
    // ==================================================
    // KHÔNG CÓ DỮ LIỆU
    // ==================================================
    if (
        filteredData.length === 0
    ) {
        emptyMessage.style.display =
            "block";
        recordCount.textContent =
            "0 lượt";
        return;
    }
    emptyMessage.style.display =
        "none";
    // ==================================================
    // ĐẢO NGƯỢC
    // MỚI NHẤT HIỂN THỊ TRƯỚC
    // ==================================================
    const reversedData =
        [...filteredData].reverse();
    // ==================================================
    // TẠO TỪNG DÒNG
    // ==================================================
    reversedData.forEach(
        (vehicle, index) => {
            const row =
                document.createElement(
                    "tr"
                );
            let typeText;
            let typeClass;
            if (
                vehicle.type === "in"
            ) {
                typeText =
                    "Xe vào";
                typeClass =
                    "type-in";
            }
            else {
                typeText =
                    "Xe ra";
                typeClass =
                    "type-out";
            }
            row.innerHTML = `
                <td>
                    ${index + 1}
                </td>
                <td>
                    <strong>
                        ${vehicle.plateNumber}
                    </strong>
                </td>
                <td>
                    ${vehicle.slotName}
                </td>
                <td>
                    <span class="vehicle-type ${typeClass}">
                        ${typeText}
                    </span>
                </td>
                <td>
                    ${vehicle.time}
                </td>
            `;
            tableBody.appendChild(
                row
            );
        }
    );
    // Tổng số bản ghi sau khi lọc
    recordCount.textContent =
        `${filteredData.length} lượt`;
}

// 5. LỌC THEO LOẠI

vehicleFilter.addEventListener(
    "change",
    function () {
        renderTable();
    }
);

// 6. TÌM KIẾM BIỂN SỐ

plateSearch.addEventListener(
    "input",
    function () {
        renderTable();
    }
);

// 7. KHỞI TẠO

updateStatistics();
renderTable();

// 8. TỰ ĐỘNG CẬP NHẬT

setInterval(
    function () {
        updateStatistics();
        renderTable();
    },
    1000
);