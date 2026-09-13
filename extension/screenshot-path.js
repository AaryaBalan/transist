// Match only GNOME Shell's screenshot directory, not the Pictures folder itself.
export function screenshotPath(parts, pictures, folderName, destination) {
    return parts.length === 2 && parts[0] === pictures && parts[1] === folderName
        ? destination : null;
}
