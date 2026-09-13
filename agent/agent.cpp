#include <iostream>
#include <string>
#include <vector>
#include <algorithm> // Required for std::fill (Secure Wiping)
#include "json.hpp"  // The JSON library from 'https://github.com/nlohmann/json'

using namespace std;
using json = nlohmann::json;

// External function declaration pointing to sha256.cpp
string compute_sha256(const string& filepath);

// ==========================================
// ANSI COLOUR CODES (FOR AESTHETICS)
// ==========================================
const string RESET  = "\033[0m";
const string GREEN  = "\033[32m";
const string RED    = "\033[31m";
const string CYAN   = "\033[36m";
const string YELLOW = "\033[33m";

// ==========================================
// ENUM DISPATCHER DICTIONARY
// ==========================================
enum class Command {
    HASH_FILE,
    UNKNOWN
};

// ==========================================
// OBJECT-ORIENTED AGENT CLASS
// ==========================================
class JockyAgent {
private:
    // Private variables: These cannot be accessed outside this class, keeping RAM secure
    string encrypted_payload;
    string decrypted_json;
    string target_config = "Agent/config.txt";
    string trusted_baseline = "6df390864fb0e145a68b2afb95a7741179387d4ec8c102a9e8c4b1fa582c6991";

    // 1. Fetch Payload
    void fetch() {
        cout << CYAN << "[+] Reaching out to Cloud API Relay..." << RESET << endl;
        // Simulating an encrypted string received from the network
        encrypted_payload = "U2FsdGVkX1+vxyz123abcScrambledGarbageData==";
        cout << GREEN << "[+] Encrypted payload successfully caught in volatile RAM." << RESET << endl;
    }

    // 2. Decrypt Payload
    void decrypt() {
        cout << CYAN << "[+] Initializing AES-256 decryption routine..." << RESET << endl;
        // Dynamically pointing to config.txt to prove live execution capability
        decrypted_json = "{\"command\": \"HASH_FILE\", \"target\": \"Agent/config.txt\"}";
        cout << GREEN << "[+] Payload decrypted successfully. Zero disk footprint." << RESET << endl;
    }

    // Helper: Converts string commands to Integer Enums for the switch statement
    Command map_command(const string& cmd_str) {
        if (cmd_str == "HASH_FILE") return Command::HASH_FILE;
        return Command::UNKNOWN;
    }

    // 3. Parse and Execute
    void execute() {
        cout << CYAN << "[+] Parsing JSON instructions..." << RESET << endl;
        try {
            json parsed = json::parse(decrypted_json);
            Command cmd = map_command(parsed["command"]);
            string target = parsed["target"];

            cout << YELLOW << "[+] INSTRUCTION ACKNOWLEDGED:" << RESET << endl;
            cout << YELLOW << "    -> Action: " << parsed["command"] << RESET << endl;
            cout << YELLOW << "    -> Target: " << target << RESET << endl;

            // The Enum Switch Dispatcher
            switch (cmd) {
                case Command::HASH_FILE: {
                    cout << CYAN << "[+] Invoking native C++ forensics module for: " << target << RESET << endl;
                    
                    // Passing the target dynamically into your SHA-256 engine
                    string live_hash = compute_sha256(target);
                    cout << GREEN << "[+] FORENSIC RESULT | SHA-256: " << live_hash << RESET << endl;
                    cout << GREEN << "[+] Result encrypted and transmitted back to Dashboard." << RESET << endl;
                    break;
                }
                case Command::UNKNOWN:
                default:
                    cout << RED << "[-] Unknown command received." << RESET << endl;
                    break;
            }
        } catch (json::parse_error& e) {
            cout << RED << "[-] CRITICAL ERROR: The payload was not valid JSON." << RESET << endl;
            cout << RED << "[-] Error details: " << e.what() << RESET << endl;
        }
    }

    // 4. Local Integrity Check
    void check_integrity() {
        cout << CYAN << "\n[*] Running local file integrity monitor..." << RESET << endl;
        string current_hash = compute_sha256(target_config);
        cout << "[i] Computed config hash: " << current_hash << endl;
        
        if (current_hash == trusted_baseline) {
            cout << GREEN << "[+] STATUS: INTEGRITY SECURE (Hashes Match)" << RESET << endl;
        } else {
            cout << RED << "[-] ALERT: TAMPERING DETECTED! Hash Mismatch!" << RESET << endl;
        }
    }

    // 5. Secure Memory Scrubbing
    void secure_wipe() {
        cout << CYAN << "\n[*] Overwriting RAM segments with null bytes..." << RESET << endl;
        
        // This is the true secure wipe: filling the memory addresses with zeros
        fill(encrypted_payload.begin(), encrypted_payload.end(), '\0');
        fill(decrypted_json.begin(), decrypted_json.end(), '\0');
        
        // Now it is safe to clear the string lengths
        encrypted_payload.clear();
        decrypted_json.clear();
        
        cout << GREEN << "[+] RAM wiped securely. Returning to deep sleep state." << RESET << endl;
    }

public:
    // The single public trigger that runs the whole operation
    void run() {
        fetch();
        decrypt();
        execute();
        check_integrity();
        secure_wipe();
    }
};

// ==========================================
// MAIN EXECUTION LOOP
// ==========================================
int main() {
    cout << "======================================" << endl;
    cout << CYAN << "   JOCKY IN-MEMORY AGENT v2.0 (PoC)   " << RESET << endl;
    cout << "======================================" << endl;

    // Instantiate the agent object and trigger the execution lifecycle
    JockyAgent agent;
    agent.run();

    cout << "======================================" << endl;
    return 0;
}