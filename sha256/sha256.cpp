#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <exception>
#include "picosha2.h" // The trusted MIT-licensed math library

// Unified ANSI Color Codes
const std::string RESET  = "\033[0m";
const std::string GREEN  = "\033[32m";
const std::string RED    = "\033[31m";
const std::string CYAN   = "\033[36m";

namespace Logger {
    void info(const std::string& message) {
        std::cout << CYAN << "[i] " << message << RESET << "\n";
    }

    void error(const std::string& message) {
        std::cerr << RED << "[-] " << message << RESET << "\n";
    }

    void success(const std::string& message) {
        std::cout << GREEN << "[+] " << message << RESET << "\n";
    }
}

// ==========================================
// CORE FORENSICS MODULE
// ==========================================
std::string compute_sha256(const std::string& filepath) {
    Logger::info("Initializing native forensics module...");
    Logger::info("Target acquired: " + filepath);

    // 1. Open the file in raw binary mode
    std::ifstream file(filepath, std::ios::binary);
    
    // 2. Safety Check
    if (!file) {
        Logger::error("CRITICAL: Target file locked, missing, or access denied.");
        return "ERROR_FILE_ACCESS";
    }

    Logger::info("Stream opened successfully. Computing SHA-256 via buffered I/O...");

    std::string hash_result;
    
    try {
        // 3. Advanced Algorithmic Execution: 8KB Chunk Buffering
        // This prevents memory overload when hashing massive files
        picosha2::hash256_one_by_one hasher;
        
        const size_t buffer_size = 8192; // 8KB buffer
        std::vector<char> buffer(buffer_size);
        
        while (file.read(buffer.data(), buffer.size())) {
            hasher.process(buffer.begin(), buffer.end());
        }
        
        // Process the remaining bytes that didn't perfectly fill the last 8KB block
        if (file.gcount() > 0) {
            hasher.process(buffer.begin(), buffer.begin() + file.gcount());
        }
        
        hasher.finish();
        picosha2::get_hash_hex_string(hasher, hash_result);
        std::fill(buffer.begin(),buffer.end(),'\0');

    } catch (const std::exception& e) {
        // 4. Enterprise Crash Protection
        Logger::error("CRITICAL: Hashing engine failure.");
        return "ERROR_HASH_COMPUTATION";
    }

    Logger::success("Cryptographic hashing complete.");
    return hash_result;
}