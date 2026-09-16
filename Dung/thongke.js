
// SMART PARKING - THONGKE.JS


// 1. CẤU HÌNH

const TOTAL_SLOTS = 60;
const AREA_SIZE = 20;

// 2. LẤY PHẦN TỬ HTML

const timeRange =
    document.getElementById(
        "time-range"
    );
const totalSlotsElement =
    document.getElementById(
        "total-slots"
    );
const occupiedSlotsElement =
    document.getElementById(
        "occupied-slots"
    );
const availableSlotsElement =
    document.getElementById(
        "available-slots"
    );
const occupiedPercentElement =
    document.getElementById(
        "occupied-percent"
    );
const totalMovementsElement =
    document.getElementById(
        "total-movements"
    );
const periodLabel =
    document.getElementById(
        "period-label"
    );
const chartDescription =
    document.getElementById(
        "chart-description"
    );
const periodInElement =
    document.getElementById(
        "period-in"
    );
const periodOutElement =
    document.getElementById(
        "period-out"
    );
const periodTotalElement =
    document.getElementById(
        "period-total"
    );
const canvas =
    document.getElementById(
        "movement-chart"
    );
const ctx =
    canvas.getContext("2d");

// 3. LẤY DỮ LIỆU

function getVehicleData() {
    return JSON.parse(
        localStorage.getItem(
            "vehicleData"
        )
    ) || [];
}

// 4. LẤY TIMESTAMP

function getTimestamp(vehicle) {
    if (
        vehicle.timestamp &&
        !isNaN(vehicle.timestamp)
    ) {
        return Number(
            vehicle.timestamp
        );
    }
    return 0;
}

// 5. LẤY NGÀY KHÔNG CÓ GIỜ

function startOfDay(date) {
    const result =
        new Date(date);
    result.setHours(
        0,
        0,
        0,
        0
    );
    return result;
}

// 6. KIỂM TRA HÔM NAY

function isToday(timestamp) {
    if (!timestamp) {
        return false;
    }
    const date =
        new Date(timestamp);
    const today =
        new Date();
    return (
        date.getFullYear() ===
        today.getFullYear()
        &&
        date.getMonth() ===
        today.getMonth()
        &&
        date.getDate() ===
        today.getDate()
    );
}

// 7. LẤY DỮ LIỆU THEO KHOẢNG THỜI GIAN

function getPeriodData() {
    const data =
        getVehicleData();
    const range =
        timeRange.value;
    // Toàn bộ dữ liệu
    if (range === "all") {
        return data;
    }
    const now =
        new Date();
    const today =
        startOfDay(now);
    let startDate;
    // ==============================================
    // HÔM NAY
    // ==============================================
    if (range === "today") {
        startDate =
            today;
    }
    // ==============================================
    // 7 NGÀY
    // ==============================================
    else if (range === "7days") {
        startDate =
            new Date(today);
        startDate.setDate(
            startDate.getDate() - 6
        );
    }
    // ==============================================
    // 30 NGÀY
    // ==============================================
    else {
        startDate =
            new Date(today);
        startDate.setDate(
            startDate.getDate() - 29
        );
    }
    return data.filter(
        vehicle => {
            const timestamp =
                getTimestamp(vehicle);
            if (!timestamp) {
                return false;
            }
            return (
                timestamp >=
                startDate.getTime()
            );
        }
    );
}

// 8. TÌM XE ĐANG Ở TRONG BÃI

function getCurrentVehicles() {
    const data =
        getVehicleData();
    /*
        Mỗi biển số chỉ lấy giao dịch
        mới nhất.
        Nếu giao dịch cuối là "in"
        → xe đang ở trong bãi.
        Nếu giao dịch cuối là "out"
        → xe đã rời bãi.
    */
    const latestVehicles =
        new Map();
    data.forEach(
        vehicle => {
            const plate =
                vehicle.plateNumber;
            if (!plate) {
                return;
            }
            const old =
                latestVehicles.get(
                    plate
                );
            if (
                !old ||
                getTimestamp(vehicle) >
                getTimestamp(old)
            ) {
                latestVehicles.set(
                    plate,
                    vehicle
                );
            }
        }
    );
    return Array.from(
        latestVehicles.values()
    ).filter(
        vehicle =>
            vehicle.type === "in"
    );
}

// 9. TÍNH THỐNG KÊ TỔNG

function updateOverview() {
    const currentVehicles =
        getCurrentVehicles();
    const occupied =
        currentVehicles.length;
    const available =
        Math.max(
            TOTAL_SLOTS - occupied,
            0
        );
    const percentage =
        TOTAL_SLOTS === 0
            ? 0
            : Math.round(
                (
                    occupied /
                    TOTAL_SLOTS
                ) * 100
            );
    const periodData =
        getPeriodData();
    totalSlotsElement.textContent =
        TOTAL_SLOTS;
    occupiedSlotsElement.textContent =
        occupied;
    availableSlotsElement.textContent =
        available;
    occupiedPercentElement.textContent =
        `${percentage}% công suất`;
    totalMovementsElement.textContent =
        periodData.length;
    periodInElement.textContent =
        periodData.filter(
            vehicle =>
                vehicle.type === "in"
        ).length;
    periodOutElement.textContent =
        periodData.filter(
            vehicle =>
                vehicle.type === "out"
        ).length;
    periodTotalElement.textContent =
        periodData.length;
}

// 10. THỐNG KÊ THEO KHU

function updateAreaStatistics() {
    const currentVehicles =
        getCurrentVehicles();
    const areaData = {
        A: 0,
        B: 0,
        C: 0
    };
    currentVehicles.forEach(
        vehicle => {
            const slot =
                (
                    vehicle.slotName ||
                    ""
                ).toUpperCase();
            if (slot.startsWith("A")) {
                areaData.A++;
            }
            else if (
                slot.startsWith("B")
            ) {
                areaData.B++;
            }
            else if (
                slot.startsWith("C")
            ) {
                areaData.C++;
            }
        }
    );
    updateOneArea(
        "a",
        areaData.A
    );
    updateOneArea(
        "b",
        areaData.B
    );
    updateOneArea(
        "c",
        areaData.C
    );
}

// 11. CẬP NHẬT MỘT KHU

function updateOneArea(
    area,
    occupied
) {
    const available =
        Math.max(
            AREA_SIZE - occupied,
            0
        );
    const percentage =
        Math.round(
            (
                occupied /
                AREA_SIZE
            ) * 100
        );
    document.getElementById(
        `area-${area}-occupied`
    ).textContent =
        occupied;
    document.getElementById(
        `area-${area}-available`
    ).textContent =
        available;
    document.getElementById(
        `area-${area}-percent`
    ).textContent =
        `${percentage}%`;
    document.getElementById(
        `area-${area}-progress`
    ).style.width =
        `${percentage}%`;
}

// 12. TÊN KHOẢNG THỜI GIAN

function getPeriodName() {
    switch (
        timeRange.value
    ) {
        case "today":
            return "Hôm nay";
        case "7days":
            return "7 ngày qua";
        case "30days":
            return "30 ngày qua";
        case "all":
            return "Toàn bộ thời gian";
        default:
            return "Hôm nay";
    }
}

// 13. CHUẨN BỊ DỮ LIỆU BIỂU ĐỒ

function getChartData() {
    const data =
        getPeriodData();
    const range =
        timeRange.value;
    const result = [];
    // ==============================================
    // HÔM NAY
    // ==============================================
    if (range === "today") {
        for (
            let hour = 0;
            hour < 24;
            hour++
        ) {
            result.push({
                label:
                    `${String(hour).padStart(2, "0")}h`,
                in: 0,
                out: 0
            });
        }
        data.forEach(
            vehicle => {
                const timestamp =
                    getTimestamp(vehicle);
                if (!timestamp) {
                    return;
                }
                const date =
                    new Date(timestamp);
                const hour =
                    date.getHours();
                if (
                    vehicle.type === "in"
                ) {
                    result[hour].in++;
                }
                else if (
                    vehicle.type === "out"
                ) {
                    result[hour].out++;
                }
            }
        );
        return result;
    }
    // ==============================================
    // 7 NGÀY
    // ==============================================
    if (range === "7days") {
        return createDailyChart(
            data,
            7
        );
    }
    // ==============================================
    // 30 NGÀY
    // ==============================================
    if (range === "30days") {
        return createDailyChart(
            data,
            30
        );
    }
    // ==============================================
    // TOÀN BỘ
    // ==============================================
    return createAllTimeChart(
        data
    );
}

// 14. BIỂU ĐỒ THEO NGÀY

function createDailyChart(
    data,
    numberOfDays
) {
    const result = [];
    const today =
        startOfDay(
            new Date()
        );
    for (
        let i = numberOfDays - 1;
        i >= 0;
        i--
    ) {
        const date =
            new Date(today);
        date.setDate(
            date.getDate() - i
        );
        result.push({
            date:
                date,
            label:
                `${String(
                    date.getDate()
                ).padStart(2, "0")}/${
                    String(
                        date.getMonth() + 1
                    ).padStart(2, "0")
                }`,
            in: 0,
            out: 0
        });
    }
    data.forEach(
        vehicle => {
            const timestamp =
                getTimestamp(vehicle);
            if (!timestamp) {
                return;
            }
            const vehicleDate =
                startOfDay(
                    new Date(timestamp)
                );
            const item =
                result.find(
                    day =>
                        day.date.getTime() ===
                        vehicleDate.getTime()
                );
            if (!item) {
                return;
            }
            if (
                vehicle.type === "in"
            ) {
                item.in++;
            }
            else if (
                vehicle.type === "out"
            ) {
                item.out++;
            }
        }
    );
    return result;
}

// 15. BIỂU ĐỒ TOÀN BỘ

function createAllTimeChart(
    data
) {
    if (data.length === 0) {
        return [];
    }
    const grouped = {};
    data.forEach(
        vehicle => {
            const timestamp =
                getTimestamp(vehicle);
            if (!timestamp) {
                return;
            }
            const date =
                new Date(timestamp);
            const key =
                `${date.getFullYear()}-${
                    String(
                        date.getMonth() + 1
                    ).padStart(2, "0")
                }-${
                    String(
                        date.getDate()
                    ).padStart(2, "0")
                }`;
            if (!grouped[key]) {
                grouped[key] = {
                    date: date,
                    in: 0,
                    out: 0
                };
            }
            if (
                vehicle.type === "in"
            ) {
                grouped[key].in++;
            }
            else if (
                vehicle.type === "out"
            ) {
                grouped[key].out++;
            }
        }
    );
    return Object.keys(grouped)
        .sort()
        .map(
            key => {
                const item =
                    grouped[key];
                return {
                    label:
                        `${String(
                            item.date.getDate()
                        ).padStart(2, "0")}/${
                            String(
                                item.date.getMonth() + 1
                            ).padStart(2, "0")
                        }`,
                    in:
                        item.in,
                    out:
                        item.out
                };
            }
        );
}

// 16. VẼ BIỂU ĐỒ

function drawChart() {
    const data =
        getChartData();
    const rect =
        canvas.getBoundingClientRect();
    const width =
        rect.width;
    const height =
        rect.height;
    const devicePixelRatio =
        window.devicePixelRatio || 1;
    canvas.width =
        width *
        devicePixelRatio;
    canvas.height =
        height *
        devicePixelRatio;
    ctx.setTransform(
        devicePixelRatio,
        0,
        0,
        devicePixelRatio,
        0,
        0
    );
    ctx.clearRect(
        0,
        0,
        width,
        height
    );
    if (data.length === 0) {
        ctx.font =
            "15px Arial";
        ctx.textAlign =
            "center";
        ctx.fillStyle =
            "#888";
        ctx.fillText(
            "Chưa có dữ liệu",
            width / 2,
            height / 2
        );
        return;
    }
    const padding = {
        top: 25,
        right: 25,
        bottom: 45,
        left: 45
    };
    const chartWidth =
        width -
        padding.left -
        padding.right;
    const chartHeight =
        height -
        padding.top -
        padding.bottom;
    const maxValue =
        Math.max(
            ...data.map(
                item =>
                    Math.max(
                        item.in,
                        item.out
                    )
            ),
            1
        );
    const yMax =
        Math.max(
            maxValue,
            5
        );
    // ==============================================
    // GRID
    // ==============================================
    ctx.strokeStyle =
        "#e9edf2";
    ctx.lineWidth =
        1;
    ctx.font =
        "11px Arial";
    ctx.fillStyle =
        "#888";
    ctx.textAlign =
        "right";
    for (
        let i = 0;
        i <= 5;
        i++
    ) {
        const value =
            Math.round(
                (
                    yMax / 5
                ) * i
            );
        const y =
            padding.top +
            chartHeight -
            (
                value /
                yMax
            ) *
            chartHeight;
        ctx.beginPath();
        ctx.moveTo(
            padding.left,
            y
        );
        ctx.lineTo(
            width -
            padding.right,
            y
        );
        ctx.stroke();
        ctx.fillText(
            value,
            padding.left - 8,
            y + 4
        );
    }
    // ==============================================
    // TÍNH ĐIỂM
    // ==============================================
    const step =
        data.length === 1
            ? chartWidth
            : chartWidth /
              (
                  data.length - 1
              );
    function getX(index) {
        return (
            padding.left +
            index * step
        );
    }
    function getY(value) {
        return (
            padding.top +
            chartHeight -
            (
                value /
                yMax
            ) *
            chartHeight
        );
    }
    // ==============================================
    // VẼ LINE
    // ==============================================
    drawLine(
        data,
        "in",
        getX,
        getY,
        width
    );
    drawLine(
        data,
        "out",
        getX,
        getY,
        width
    );
    // ==============================================
    // LABEL TRỤC X
    // ==============================================
    ctx.fillStyle =
        "#888";
    ctx.font =
        "11px Arial";
    ctx.textAlign =
        "center";
    let labelStep = 1;
    if (data.length > 15) {
        labelStep = 5;
    }
    else if (
        data.length > 8
    ) {
        labelStep = 2;
    }
    data.forEach(
        (item, index) => {
            if (
                index %
                labelStep !== 0
            ) {
                return;
            }
            const x =
                getX(index);
            ctx.fillText(
                item.label,
                x,
                height - 15
            );
        }
    );
    // ==============================================
    // CHÚ THÍCH
    // ==============================================
    drawLegend(
        width
    );
}

// 17. VẼ MỘT ĐƯỜNG

function drawLine(
    data,
    type,
    getX,
    getY
) {
    ctx.beginPath();
    data.forEach(
        (item, index) => {
            const x =
                getX(index);
            const y =
                getY(
                    item[type]
                );
            if (index === 0) {
                ctx.moveTo(
                    x,
                    y
                );
            }
            else {
                ctx.lineTo(
                    x,
                    y
                );
            }
        }
    );
    ctx.strokeStyle =
        type === "in"
            ? "#1e3c72"
            : "#e05a5a";
    ctx.lineWidth =
        3;
    ctx.lineJoin =
        "round";
    ctx.lineCap =
        "round";
    ctx.stroke();
    // ==============================================
    // ĐIỂM
    // ==============================================
    data.forEach(
        (item, index) => {
            const x =
                getX(index);
            const y =
                getY(
                    item[type]
                );
            ctx.beginPath();
            ctx.arc(
                x,
                y,
                4,
                0,
                Math.PI * 2
            );
            ctx.fillStyle =
                type === "in"
                    ? "#1e3c72"
                    : "#e05a5a";
            ctx.fill();
        }
    );
}

// 18. LEGEND

function drawLegend(
    width
) {
    const y = 12;
    ctx.font =
        "12px Arial";
    ctx.textAlign =
        "left";
    ctx.fillStyle =
        "#1e3c72";
    ctx.fillRect(
        width - 150,
        y - 8,
        10,
        10
    );
    ctx.fillStyle =
        "#555";
    ctx.fillText(
        "Xe vào",
        width - 132,
        y + 2
    );
    ctx.fillStyle =
        "#e05a5a";
    ctx.fillRect(
        width - 75,
        y - 8,
        10,
        10
    );
    ctx.fillStyle =
        "#555";
    ctx.fillText(
        "Xe ra",
        width - 57,
        y + 2
    );
}

// 19. CẬP NHẬT TEXT BIỂU ĐỒ

function updateChartDescription() {
    const name =
        getPeriodName();
    periodLabel.textContent =
        name;
    chartDescription.textContent =
        `Thống kê trong ${name.toLowerCase()}`;
}

// 20. CẬP NHẬT TOÀN BỘ

function updateStatistics() {
    updateOverview();
    updateAreaStatistics();
    updateChartDescription();
    drawChart();
}

// 21. ĐỔI KHOẢNG THỜI GIAN

timeRange.addEventListener(
    "change",
    function () {
        updateStatistics();
    }
);

// 22. KHI LOCALSTORAGE THAY ĐỔI

window.addEventListener(
    "storage",
    function (event) {
        if (
            event.key ===
            "vehicleData"
        ) {
            updateStatistics();
        }
    }
);

// 23. KHI QUAY LẠI TRANG

window.addEventListener(
    "pageshow",
    function () {
        updateStatistics();
    }
);

// 24. RESIZE

window.addEventListener(
    "resize",
    function () {
        drawChart();
    }
);

// 25. KHỞI TẠO

updateStatistics();