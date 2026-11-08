import XCTest

/// The web app relies on window.confirm / prompt / alert (New song, delete
/// block, name a block). WKWebView answers them "no" unless the app shows
/// them, which made those buttons do nothing on the phone.
final class JSPanelUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["-js-panel-test"]
        app.launch()
    }

    private func tapWebButton(_ label: String) {
        let button = app.webViews.buttons[label]
        XCTAssertTrue(button.waitForExistence(timeout: 15), "\(label) button")
        button.tap()
    }

    private func assertOutput(_ text: String) {
        let out = app.webViews.staticTexts[text]
        XCTAssertTrue(out.waitForExistence(timeout: 10), "expected \(text)")
    }

    func testConfirmOKAndCancel() {
        tapWebButton("Confirm")
        let alert = app.alerts.firstMatch
        XCTAssertTrue(alert.waitForExistence(timeout: 5))
        XCTAssertTrue(alert.staticTexts["Start a new song?"].exists)
        alert.buttons["OK"].tap()
        assertOutput("confirm:true")

        tapWebButton("Confirm")
        XCTAssertTrue(app.alerts.firstMatch.waitForExistence(timeout: 5))
        app.alerts.firstMatch.buttons["Cancel"].tap()
        assertOutput("confirm:false")
    }

    func testPromptReturnsTypedText() {
        tapWebButton("Prompt")
        let alert = app.alerts.firstMatch
        XCTAssertTrue(alert.waitForExistence(timeout: 5))
        let field = alert.textFields.firstMatch
        XCTAssertEqual(field.value as? String, "Verse edit")
        field.tap()
        field.typeText(" 2")
        alert.buttons["OK"].tap()
        assertOutput("prompt:Verse edit 2")
    }

    func testAlertShowsAndContinues() {
        tapWebButton("Alert")
        let alert = app.alerts.firstMatch
        XCTAssertTrue(alert.waitForExistence(timeout: 5))
        alert.buttons["OK"].tap()
        assertOutput("alert:done")
    }
}
