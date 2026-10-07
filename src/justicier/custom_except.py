# justicier - Automated employee justifications
# Copyright (C) 2026  Aleix Mariné Tena (AleixMT), Carles de la Cuadra
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


"""Domain-specific exception hierarchy for Justicier."""


class ArgumentDateError(Exception):
    """Raised when a date argument is missing or cannot be parsed."""


class ArgumentNafNotPresentError(Exception):
    """Raised when the provided NAF is not found in the authorised employee list."""


class ArgumentAuthorError(Exception):
    """Raised when the request author is not in the authorised user list."""


class ArgumentNafInvalidError(Exception):
    """Raised when a NAF or NIF string does not conform to the expected format."""


class UndefinedSalaryTypeError(Exception):
    """Raised when a salary page cannot be classified."""


class UndefinedProofTypeError(Exception):
    """Raised when a proof page cannot be classified."""


class UndefinedInputTypeError(Exception):
    """Raised when an unsupported input location type is supplied."""


class BadSharepointListUpdateRequestError(Exception):
    """Raised when a SharePoint list item update returns a non-200 status."""


class PersonDoesNotExistInSharepointError(Exception):
    """Raised when an employee cannot be found in the SharePoint list."""


class SecretCouldNotBeReadFromAnySourceError(Exception):
    """Raised when a secret cannot be read from any source."""


class InvalidFilenameError(Exception):
    """Raised when a document filename does not conform to the expected naming convention."""
