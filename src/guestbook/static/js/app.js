/* Guestbook — minimal JS for dynamic form behavior */

document.addEventListener('DOMContentLoaded', function () {
    var addBtn = document.getElementById('add-member-btn');
    if (addBtn) {
        addBtn.addEventListener('click', addMember);
    }

    // Use event delegation for remove buttons (handles dynamically added rows)
    var container = document.getElementById('members-container');
    if (container) {
        container.addEventListener('click', function (e) {
            var btn = e.target.closest('.remove-member-btn');
            if (btn) {
                removeMember(btn);
            }
        });
    }

    // Family member rows (profile page)
    var addFamilyBtn = document.getElementById('add-family-btn');
    if (addFamilyBtn) {
        addFamilyBtn.addEventListener('click', addFamilyMember);
    }
    var familyContainer = document.getElementById('family-members-container');
    if (familyContainer) {
        familyContainer.addEventListener('click', function (e) {
            var btn = e.target.closest('.remove-family-btn');
            if (btn) {
                var rows = familyContainer.querySelectorAll('.family-member-row');
                if (rows.length > 1) {
                    btn.closest('.family-member-row').remove();
                }
            }
        });
    }

    // Schedule rows (admin event form)
    var addScheduleBtn = document.getElementById('add-schedule-btn');
    if (addScheduleBtn) {
        addScheduleBtn.addEventListener('click', addScheduleRow);
    }
    var scheduleContainer = document.getElementById('schedule-container');
    if (scheduleContainer) {
        scheduleContainer.addEventListener('click', function (e) {
            var btn = e.target.closest('.remove-schedule-btn');
            if (btn) {
                var rows = scheduleContainer.querySelectorAll('.schedule-row');
                if (rows.length > 1) {
                    btn.closest('.schedule-row').remove();
                }
            }
        });
    }

    // Household join redirect
    var joinBtn = document.getElementById('join-household-btn');
    if (joinBtn) {
        joinBtn.addEventListener('click', function () {
            var code = document.getElementById('household-code').value.trim();
            if (code) {
                window.location.href = '/household/join/' + code;
            }
        });
    }

    // Auto-submit role dropdowns
    document.querySelectorAll('.auto-submit-role').forEach(function (select) {
        select.addEventListener('change', function () {
            this.form.submit();
        });
    });

    // Confirm before deleting users
    document.querySelectorAll('.confirm-delete-form').forEach(function (form) {
        form.addEventListener('submit', function (e) {
            var email = this.dataset.email || 'this user';
            if (!confirm('Delete user ' + email + '? This will also delete their RSVPs.')) {
                e.preventDefault();
            }
        });
    });
});

function addMember() {
    var container = document.getElementById('members-container');
    if (!container) return;

    var rows = container.querySelectorAll('.member-row');
    var index = rows.length;

    var row = document.createElement('div');
    row.className = 'member-row';
    row.dataset.index = index;
    row.innerHTML =
        '<div class="grid">' +
            '<input type="text" name="extra_name[]" placeholder="Name" required>' +
            '<select name="extra_food_preference[]">' +
                '<option value="">Food preference...</option>' +
                '<option value="omnivore">Omnivore</option>' +
                '<option value="vegetarian">Vegetarian</option>' +
                '<option value="vegan">Vegan</option>' +
            '</select>' +
        '</div>' +
        '<div class="grid">' +
            '<input type="text" name="extra_dietary_restrictions[]" placeholder="Dietary restrictions (e.g. nut allergy)" value="">' +
            '<label style="margin:0;white-space:nowrap">' +
                '<input type="checkbox" name="extra_alcohol_' + index + '" value="1" style="margin-right:0.25rem">' +
                'Alcohol' +
            '</label>' +
            '<button type="button" class="outline secondary remove-member-btn">Remove</button>' +
        '</div>';
    container.appendChild(row);
}

function addFamilyMember() {
    var container = document.getElementById('family-members-container');
    if (!container) return;

    var rows = container.querySelectorAll('.family-member-row');
    var index = rows.length;

    var row = document.createElement('div');
    row.className = 'member-row family-member-row';
    row.dataset.index = index;
    row.innerHTML =
        '<div class="grid">' +
            '<input type="text" name="family_name[]" placeholder="Name" required>' +
            '<select name="family_food_preference[]">' +
                '<option value="">Food preference...</option>' +
                '<option value="omnivore">Omnivore</option>' +
                '<option value="vegetarian">Vegetarian</option>' +
                '<option value="vegan">Vegan</option>' +
            '</select>' +
        '</div>' +
        '<div class="grid">' +
            '<input type="text" name="family_dietary_restrictions[]" placeholder="Dietary restrictions (e.g. nut allergy)" value="">' +
            '<label style="margin:0;white-space:nowrap">' +
                '<input type="checkbox" name="family_alcohol_' + index + '" value="1" style="margin-right:0.25rem">' +
                'Alcohol' +
            '</label>' +
            '<button type="button" class="outline secondary remove-family-btn">Remove</button>' +
        '</div>';
    container.appendChild(row);
}

function addScheduleRow() {
    var container = document.getElementById('schedule-container');
    if (!container) return;
    var row = document.createElement('div');
    row.className = 'schedule-row grid';
    row.innerHTML =
        '<input type="text" name="schedule_time[]" placeholder="Time (e.g. 5:00 PM)">' +
        '<input type="text" name="schedule_activity[]" placeholder="Activity (e.g. Dinner served)">' +
        '<button type="button" class="outline secondary remove-schedule-btn">Remove</button>';
    container.appendChild(row);
}

function removeMember(button) {
    var row = button.closest('.member-row');
    if (row) row.remove();
}
