// SMART PARKING - PARKING.JS

document.addEventListener("DOMContentLoaded", function () {

    // ======================================================
    // 1. LẤY CÁC PHẦN TỬ HTML
    // ======================================================

    const slots = document.querySelectorAll(".parking-slot");

    const totalSlotsElement =
        document.getElementById("total-slots");

    const availableSlotsElement =
        document.getElementById("available-slots");

    const occupiedSlotsElement =
        document.getElementById("occupied-slots");

    const maintenanceSlotsElement =
        document.getElementById("maintenance-slots");

    const areaSelect =
        document.getElementById("area");


    // ======================================================
    // 2. DỮ LIỆU XE RA VÀO
    // ======================================================

    function getVehicleData() {
        return JSON.parse(
            localStorage.getItem("vehicleData")
        ) || [];
    }

    function saveVehicleData(data) {
        localStorage.setItem(
            "vehicleData",
            JSON.stringify(data)
        );
    }

    function recordVehicle(
        plateNumber,
        slotName,
        type
    ) {
        const vehicleData = getVehicleData();

        const now = new Date();

        const record = {
            plateNumber: plateNumber,
            slotName: slotName,
            type: type,
            timestamp: now.getTime(),
            time: now.toLocaleString("vi-VN")
        };

        vehicleData.push(record);

        saveVehicleData(vehicleData);
    }


    // ======================================================
    // 3. DỮ LIỆU TRẠNG THÁI BÃI ĐỖ
    // ======================================================

    function getParkingState() {
        return JSON.parse(
            localStorage.getItem("parkingState")
        ) || {};
    }

    function saveParkingState() {

        const parkingState = {};

        slots.forEach(function (slot) {

            const slotName =
                slot.querySelector("strong").textContent;

            let status = "available";

            if (slot.classList.contains("occupied")) {
                status = "occupied";
            }
            else if (slot.classList.contains("maintenance")) {
                status = "maintenance";
            }

            parkingState[slotName] = {
                status: status,
                plate: slot.dataset.plate || null
            };

        });

        localStorage.setItem(
            "parkingState",
            JSON.stringify(parkingState)
        );
    }


    // ======================================================
    // 4. KHÔI PHỤC TRẠNG THÁI BÃI ĐỖ
    // ======================================================

    function restoreParkingState() {

        const parkingState = getParkingState();

        if (Object.keys(parkingState).length === 0) {
            return;
        }

        slots.forEach(function (slot) {

            const slotName =
                slot.querySelector("strong").textContent;

            const savedSlot =
                parkingState[slotName];

            if (!savedSlot) {
                return;
            }

            // Xóa trạng thái cũ
            slot.classList.remove(
                "available",
                "occupied",
                "maintenance"
            );

            // Thêm trạng thái đã lưu
            slot.classList.add(
                savedSlot.status
            );

            // Cập nhật chữ trạng thái
            const statusText =
                slot.querySelector("span");

            if (savedSlot.status === "available") {
                statusText.textContent = "Trống";
            }
            else if (savedSlot.status === "occupied") {
                statusText.textContent = "Đang đỗ";
            }
            else if (savedSlot.status === "maintenance") {
                statusText.textContent = "Bảo trì";
            }

            // Khôi phục biển số
            if (
                savedSlot.status === "occupied" &&
                savedSlot.plate
            ) {
                slot.dataset.plate =
                    savedSlot.plate;
            }
            else {
                delete slot.dataset.plate;
            }

        });
    }


    // ======================================================
    // 5. CẬP NHẬT THỐNG KÊ
    // ======================================================

    function updateStatistics() {

        const total = slots.length;

        const available =
            document.querySelectorAll(
                ".parking-slot.available"
            ).length;

        const occupied =
            document.querySelectorAll(
                ".parking-slot.occupied"
            ).length;

        const maintenance =
            document.querySelectorAll(
                ".parking-slot.maintenance"
            ).length;

        totalSlotsElement.textContent =
            total;

        availableSlotsElement.textContent =
            available;

        occupiedSlotsElement.textContent =
            occupied;

        maintenanceSlotsElement.textContent =
            maintenance;
    }


    // ======================================================
    // 6. CẬP NHẬT THỐNG KÊ TỪNG KHU
    // ======================================================

    function updateAreaStatistics() {

        const sections =
            document.querySelectorAll(
                ".parking-section"
            );

        sections.forEach(function (section) {

            const areaSlots =
                section.querySelectorAll(
                    ".parking-slot"
                );

            const available =
                section.querySelectorAll(
                    ".parking-slot.available"
                ).length;

            const areaStatus =
                section.querySelector(
                    ".area-status"
                );

            if (areaStatus) {

                areaStatus.textContent =
                    `${available} / ${areaSlots.length} vị trí trống`;

            }

        });
    }


    // ======================================================
    // 7. ĐỔI TRẠNG THÁI Ô ĐỖ
    // ======================================================

    function changeSlotStatus(
        slot,
        status
    ) {

        slot.classList.remove(
            "available",
            "occupied",
            "maintenance"
        );

        slot.classList.add(status);

        const statusText =
            slot.querySelector("span");

        if (status === "available") {
            statusText.textContent = "Trống";
        }
        else if (status === "occupied") {
            statusText.textContent = "Đang đỗ";
        }
        else if (status === "maintenance") {
            statusText.textContent = "Bảo trì";
        }

        updateStatistics();

        updateAreaStatistics();

        saveParkingState();
    }


    // ======================================================
    // 8. TẠO MENU CHO Ô ĐỖ
    // ======================================================

    function showSlotMenu(slot) {

        const slotName =
            slot.querySelector("strong").textContent;

        const isAvailable =
            slot.classList.contains("available");

        const isOccupied =
            slot.classList.contains("occupied");

        const isMaintenance =
            slot.classList.contains("maintenance");


        // Nếu đã có menu thì đóng menu cũ
        closeSlotMenu();


        // Tạo menu
        const menu =
            document.createElement("div");

        menu.className = "slot-menu";


        // ==================================================
        // TIÊU ĐỀ
        // ==================================================

        const title =
            document.createElement("h3");

        title.textContent =
            `Vị trí ${slotName}`;

        menu.appendChild(title);


        // ==================================================
        // ĐỖ XE
        // ==================================================

        if (isAvailable) {

            const parkButton =
                document.createElement("button");

            parkButton.className =
                "menu-button park-button";

            parkButton.textContent =
                "🚗 Đỗ xe";


            parkButton.addEventListener(
                "click",
                function (event) {

                    event.stopPropagation();


                    // Nhập biển số
                    const plate =
                        prompt(
                            `Nhập biển số xe vào vị trí ${slotName}:`
                        );


                    // Bấm Cancel
                    if (plate === null) {
                        return;
                    }


                    // Làm sạch biển số
                    const cleanPlate =
                        plate
                            .trim()
                            .toUpperCase();


                    // Không được để trống
                    if (cleanPlate === "") {

                        alert(
                            "Vui lòng nhập biển số xe!"
                        );

                        return;
                    }


                    // Kiểm tra xe đang ở trong bãi
                    const vehicleData =
                        getVehicleData();

                    const vehicleInside =
                        vehicleData.some(
                            function (vehicle) {

                                return (
                                    vehicle.plateNumber === cleanPlate &&
                                    vehicle.type === "in"
                                );

                            }
                        );


                    if (vehicleInside) {

                        alert(
                            `Xe ${cleanPlate} đang ở trong bãi!`
                        );

                        return;
                    }


                    // Lưu biển số vào ô
                    slot.dataset.plate =
                        cleanPlate;


                    // Đổi trạng thái
                    changeSlotStatus(
                        slot,
                        "occupied"
                    );


                    // Ghi nhận xe vào
                    recordVehicle(
                        cleanPlate,
                        slotName,
                        "in"
                    );


                    alert(
                        `Xe ${cleanPlate} đã đỗ tại ${slotName}.`
                    );


                    closeSlotMenu();

                }
            );

            menu.appendChild(parkButton);
        }


        // ==================================================
        // RỜI XE
        // ==================================================

        if (isOccupied) {

            const leaveButton =
                document.createElement("button");

            leaveButton.className =
                "menu-button leave-button";

            leaveButton.textContent =
                "🚪 Rời xe";


            leaveButton.addEventListener(
                "click",
                function (event) {

                    event.stopPropagation();


                    const confirmLeave =
                        confirm(
                            `Xe tại ${slotName} sẽ rời bãi. Bạn có chắc không?`
                        );


                    if (!confirmLeave) {
                        return;
                    }


                    // Lấy biển số
                    const plate =
                        slot.dataset.plate ||
                        "Không rõ";


                    // Ghi nhận xe ra
                    recordVehicle(
                        plate,
                        slotName,
                        "out"
                    );


                    // Xóa biển số
                    delete slot.dataset.plate;


                    // Đổi trạng thái
                    changeSlotStatus(
                        slot,
                        "available"
                    );


                    alert(
                        `Xe ${plate} tại ${slotName} đã rời bãi.`
                    );


                    closeSlotMenu();

                }
            );

            menu.appendChild(leaveButton);
        }


        // ==================================================
        // BẢO TRÌ
        // ==================================================

        const maintenanceButton =
            document.createElement("button");

        maintenanceButton.className =
            "menu-button maintenance-button";


        if (isMaintenance) {

            maintenanceButton.textContent =
                "🔧 Kết thúc bảo trì";

        }
        else {

            maintenanceButton.textContent =
                "🔧 Đưa vào bảo trì";

        }


        maintenanceButton.addEventListener(
            "click",
            function (event) {

                event.stopPropagation();


                // Kết thúc bảo trì
                if (isMaintenance) {

                    changeSlotStatus(
                        slot,
                        "available"
                    );

                    alert(
                        `${slotName} đã kết thúc bảo trì.`
                    );

                }


                // Đưa vào bảo trì
                else {

                    const confirmMaintenance =
                        confirm(
                            `Đưa vị trí ${slotName} vào bảo trì?`
                        );


                    if (!confirmMaintenance) {
                        return;
                    }


                    changeSlotStatus(
                        slot,
                        "maintenance"
                    );


                    alert(
                        `${slotName} đã được đưa vào trạng thái bảo trì.`
                    );

                }


                closeSlotMenu();

            }
        );

        menu.appendChild(
            maintenanceButton
        );


        // ==================================================
        // NÚT HỦY
        // ==================================================

        const closeButton =
            document.createElement("button");

        closeButton.className =
            "menu-button close-button";

        closeButton.textContent =
            "Hủy";


        closeButton.addEventListener(
            "click",
            function (event) {

                event.stopPropagation();

                closeSlotMenu();

            }
        );


        menu.appendChild(closeButton);


        // ==================================================
        // HIỂN THỊ MENU
        // ==================================================

        document.body.appendChild(menu);
    }


    // ======================================================
    // 9. ĐÓNG MENU
    // ======================================================

    function closeSlotMenu() {

        const oldMenu =
            document.querySelector(".slot-menu");

        if (oldMenu) {
            oldMenu.remove();
        }
    }


    // ======================================================
    // 10. CLICK VÀO Ô ĐỖ
    // ======================================================

    slots.forEach(function (slot) {

        slot.addEventListener(
            "click",
            function (event) {

                event.stopPropagation();

                showSlotMenu(slot);

            }
        );

    });


    // ======================================================
    // 11. CLICK RA NGOÀI MENU
    // ======================================================

    document.addEventListener(
        "click",
        function (event) {

            const menu =
                document.querySelector(".slot-menu");

            if (!menu) {
                return;
            }


            // Click bên trong menu
            if (menu.contains(event.target)) {
                return;
            }


            // Click vào ô đỗ
            if (
                event.target.closest(".parking-slot")
            ) {
                return;
            }


            // Click nơi khác
            closeSlotMenu();

        }
    );


    // ======================================================
    // 12. LỌC KHU VỰC
    // ======================================================

    if (areaSelect) {

        areaSelect.addEventListener(
            "change",
            function () {

                const selectedArea =
                    this.value;

                const sections =
                    document.querySelectorAll(
                        ".parking-section"
                    );


                sections.forEach(
                    function (section) {

                        const area =
                            section.dataset.area;


                        if (
                            selectedArea === "all" ||
                            selectedArea === area
                        ) {

                            section.style.display =
                                "block";

                        }
                        else {

                            section.style.display =
                                "none";

                        }

                    }
                );

            }
        );

    }


    // ======================================================
    // 13. KHỞI TẠO
    // ======================================================

    restoreParkingState();

    updateStatistics();

    updateAreaStatistics();

});